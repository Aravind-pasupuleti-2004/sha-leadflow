"""WhatsApp webhook handling - core functions."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ...extensions import db
from ...models import InboundMessage, Lead, WhatsAppConsent, OutboundMessage, Activity
from ...services.validation import normalize_phone
from .provider import WhatsAppProvider
from .config import whatsapp_config

logger = logging.getLogger(__name__)

OPT_OUT_PHRASES = {
    "stop", "unsubscribe", "opt out", "remove me", "delete me",
    "no more", "quit", "cancel", "unsub", "remove"
}


def is_opt_out_message(text: str) -> bool:
    """Check if inbound message indicates opt-out intent."""
    if not text:
        return False
    normalized = text.lower().strip()
    return any(phrase in normalized for phrase in OPT_OUT_PHRASES)


def process_inbound_message(payload: dict) -> dict:
    """Process an inbound WhatsApp message webhook payload."""
    try:
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})

        if "statuses" in value:
            return _process_status_updates(value["statuses"])

        messages = value.get("messages", [])
        if not messages:
            return {"status": "ignored", "reason": "no_messages"}

        results = []
        for msg in messages:
            result = _process_single_message(msg, value.get("contacts", []))
            results.append(result)

        return {"status": "processed", "messages": results}

    except Exception as e:
        logger.exception("Error processing webhook: %s", e)
        return {"status": "error", "error": str(e)}


def _process_single_message(msg: dict, contacts: list[dict]) -> dict:
    """Process a single inbound message."""
    provider_message_id = msg.get("id")
    from_number = msg.get("from")
    msg_type = msg.get("type")
    timestamp = int(msg.get("timestamp", 0))
    received_at = datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)

    existing = db.session.scalars(
        db.select(InboundMessage).where(
            InboundMessage.provider_message_id == provider_message_id
        )
    ).first()
    if existing:
        return {"status": "duplicate", "provider_message_id": provider_message_id}

    lead = None
    if from_number:
        norm = normalize_phone(from_number)
        if norm:
            lead = db.session.scalars(
                db.select(Lead).where(Lead.normalized_phone == norm)
            ).first()

    content = None
    if msg_type == "text":
        content = msg.get("text", {}).get("body")
    elif msg_type == "interactive":
        interactive = msg.get("interactive", {})
        if interactive.get("type") == "button_reply":
            content = interactive.get("button_reply", {}).get("title")
        elif interactive.get("type") == "list_reply":
            content = interactive.get("list_reply", {}).get("title")
    else:
        content = f"[{msg_type} message]"

    inbound = InboundMessage(
        lead_id=lead.id if lead else None,
        provider_message_id=provider_message_id,
        direction="inbound",
        content=content,
        received_at=received_at,
        processed=False,
    )
    db.session.add(inbound)

    if not lead:
        db.session.commit()
        return {"status": "unmatched", "provider_message_id": provider_message_id, "lead_id": None}

    opt_out = False
    if content and is_opt_out_message(content):
        opt_out = True
        inbound.opt_out_detected = True

        consent = lead.whatsapp_consent
        if consent:
            consent.opted_in = False
            consent.opted_out_at = datetime.now(timezone.utc).replace(tzinfo=None)
            consent.opt_out_reason = "user_reply"
        else:
            consent = WhatsAppConsent(
                lead_id=lead.id,
                opted_in=False,
                opted_out_at=datetime.now(timezone.utc).replace(tzinfo=None),
                opt_out_reason="user_reply",
            )
            db.session.add(consent)

        from ..jobs import cancel_pending_jobs
        cancel_pending_jobs(lead.id, "user_opted_out")

        activity = Activity(
            lead=lead,
            kind="whatsapp_opt_out",
            message=f"User opted out via WhatsApp: {content}",
        )
        db.session.add(activity)

    inbound.processed = True
    db.session.commit()

    return {
        "status": "processed",
        "provider_message_id": provider_message_id,
        "lead_id": lead.id,
        "opt_out_detected": opt_out,
    }


def _process_status_updates(statuses: list[dict]) -> dict:
    """Process delivery status webhooks."""
    for status in statuses:
        msg_id = status.get("id")
        status_type = status.get("status")
        timestamp = int(status.get("timestamp", 0))
        received_at = datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)

        outbound = db.session.scalars(
            db.select(OutboundMessage).where(OutboundMessage.provider_message_id == msg_id)
        ).first()

        if not outbound:
            continue

        outbound.status = status_type
        if status_type == "sent":
            outbound.sent_at = received_at
        elif status_type == "delivered":
            outbound.delivered_at = received_at
        elif status_type == "read":
            outbound.read_at = received_at
        elif status_type == "failed":
            outbound.error = status.get("errors", [{}])[0].get("title", "unknown")

        db.session.commit()

    return {"status": "processed", "count": len(statuses)}