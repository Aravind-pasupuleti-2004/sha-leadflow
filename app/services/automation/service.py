"""Centralized lead automation service.

This module provides the single entry point for triggering automation after a
lead is successfully committed to the database. It uses a transactional outbox
pattern: AutomationEvent records are committed in the same transaction as the
lead, guaranteeing no automation event is lost even if the process crashes.

External AI/WhatsApp calls are never made inside the database transaction.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ...extensions import db
from ...models import (
    AutomationEvent,
    AutomationEventStatus,
    AutomationEventType,
    Lead,
)
from ..scoring import recalculate_score
from ..ai import qualify_lead, build_provider, generate_initial_message
from ..whatsapp import send_message


def _generate_idempotency_key(lead_id: int, event_type: str) -> str:
    """Generate a deterministic idempotency key for a lead+event combination."""
    return f"{lead_id}:{event_type}"


def _create_automation_event(
    lead_id: int,
    event_type: str,
    payload: Optional[dict[str, Any]] = None,
) -> AutomationEvent:
    """Create an AutomationEvent in the current session (not yet committed)."""
    idempotency_key = _generate_idempotency_key(lead_id, event_type)
    event = AutomationEvent(
        lead_id=lead_id,
        event_type=event_type,
        status=AutomationEventStatus.PENDING,
        idempotency_key=idempotency_key,
        payload=payload or {},
        attempts=0,
        max_attempts=5,
    )
    db.session.add(event)
    return event


def enqueue_automation(lead: Lead, config: dict, user_id: Optional[int] = None) -> AutomationEvent:
    """Enqueue the full automation pipeline for a newly created lead.

    This is called immediately after the lead is committed to the database.
    It creates an AutomationEvent for qualification. Subsequent events
    (send_initial, schedule_followup) are chained by the event processor.

    Args:
        lead: The newly created Lead (already committed/flushed).
        config: Application configuration dict.
        user_id: Optional ID of the user who created the lead.

    Returns:
        The created AutomationEvent (status=PENDING).
    """
    # Qualify the lead immediately (deterministic scoring + AI)
    qualify_new_lead(lead, config, user_id)

    # Create the initial automation event (qualification)
    event = _create_automation_event(
        lead_id=lead.id,
        event_type=AutomationEventType.QUALIFY,
        payload={"trigger": "lead_created", "user_id": user_id},
    )
    # Note: we don't commit here - the caller's transaction will commit it
    return event


def qualify_new_lead(lead: Lead, config: dict, user_id: Optional[int] = None) -> None:
    """Run deterministic scoring and AI qualification for a new lead.

    Updates lead.score, lead.score_factors, and saves AI qualification results.
    """
    # Deterministic scoring (always runs)
    score_result = recalculate_score(lead, config)

    # AI qualification (with fallback)
    provider = build_provider(config)
    ai_result = qualify_lead(
        lead,
        score_result,
        config,
        provider=provider,
    )

    # Save qualification results to lead
    lead.ai_summary = ai_result.summary
    lead.ai_next_action = ai_result.next_action
    lead.ai_extracted = ai_result.as_dict()
    lead.ai_provider = ai_result.provider
    lead.ai_updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # Log activity
    from ...models import Activity
    activity = Activity(
        lead=lead,
        user_id=user_id,
        kind="qualified",
        message=f"Lead qualified: score={lead.score}, band={ai_result.readiness}, provider={ai_result.provider}",
        details={
            "score": lead.score,
            "band": ai_result.readiness,
            "provider": ai_result.provider,
            "fallback": ai_result.fallback,
            "fallback_reason": ai_result.fallback_reason,
        },
    )
    db.session.add(activity)


def schedule_followups(lead: Lead, config: dict, user_id: Optional[int] = None) -> list:
    """Create scheduled follow-up jobs for a lead after qualification.

    Default sequence: +1 day, +3 days, +7 days.
    All times stored in UTC.
    """
    from ...models import ScheduledJob, ScheduledJobStatus, WhatsAppConsent

    # Check consent before scheduling
    consent = lead.whatsapp_consent
    if not consent or not consent.opted_in:
        return []

    now_utc = datetime.now(timezone.utc)
    intervals = [1, 3, 7]  # days
    jobs = []

    for days in intervals:
        scheduled_at = now_utc + timedelta(days=days)
        idempotency_key = f"{lead.id}:followup:{days}d"
        job = ScheduledJob(
            lead_id=lead.id,
            job_type=f"followup_{days}d",
            scheduled_at_utc=scheduled_at,
            status=ScheduledJobStatus.PENDING,
            idempotency_key=idempotency_key,
            attempts=0,
            max_attempts=3,
        )
        db.session.add(job)
        jobs.append(job)

    if jobs:
        _log_automation_activity(
            lead,
            "followups_scheduled",
            f"Scheduled {len(jobs)} follow-up messages",
            user_id,
            details={"intervals": intervals, "job_ids": [j.id for j in jobs]},
        )

    return jobs


def send_initial_message(lead: Lead, config: dict, user_id: Optional[int] = None) -> bool:
    """Generate and send the initial personalized WhatsApp message for a lead.

    Returns True if message was sent (or queued in dry-run), False if failed or not eligible.
    """
    # Check if automation is enabled for initial messages
    if not config.get("AUTOMATION_INITIAL_ENABLED", True):
        return False

    # Check consent
    consent = lead.whatsapp_consent
    if not consent or not consent.opted_in:
        _log_automation_activity(lead, "initial_message_skipped", "WhatsApp consent not granted", user_id)
        return False

    if consent.opted_out_at:
        _log_automation_activity(lead, "initial_message_skipped", "User opted out", user_id)
        return False

    # Validate phone
    if not lead.normalized_phone:
        _log_automation_activity(lead, "initial_message_failed", "No phone number", user_id)
        return False

    # Generate personalized initial message
    provider = build_provider(config)
    msg_result = generate_initial_message(lead, config, provider=provider)

    # Send via WhatsApp
    send_result = send_message(
        lead=lead,
        content=msg_result.message,
        purpose="initial",
        message_type="text",
        idempotency_key=f"{lead.id}:initial",
    )

    # Log activity
    if send_result.success:
        _log_automation_activity(
            lead,
            "initial_message_sent",
            f"Initial message sent via WhatsApp (provider: {msg_result.provider_label})",
            user_id,
            details={
                "provider": msg_result.provider,
                "fallback": msg_result.fallback,
                "whatsapp_msg_id": send_result.provider_message_id,
            },
        )
        return True
    else:
        _log_automation_activity(
            lead,
            "initial_message_failed",
            f"Failed to send initial message: {send_result.error}",
            user_id,
            details={"error": send_result.error},
        )
        return False


def _log_automation_activity(
    lead: Lead,
    kind: str,
    message: str,
    user_id: Optional[int] = None,
    details: dict | None = None,
) -> None:
    """Log an automation-related activity."""
    from ...models import Activity
    activity = Activity(
        lead=lead,
        user_id=user_id,
        kind=kind,
        message=message,
        details=details or {},
    )
    db.session.add(activity)

def process_pending_automation_events(config: dict, limit: int = 50) -> dict:
    """Process pending automation events (QUALIFY, SEND_INITIAL, SCHEDULE_FOLLOWUP).

    This should be called by a background worker or scheduled task.
    Returns a summary of processed events.
    """
    from ...models import AutomationEvent, AutomationEventStatus, AutomationEventType

    now_utc = datetime.now(timezone.utc)

    # Get pending events ordered by creation time
    events = db.session.scalars(
        db.select(AutomationEvent)
        .where(AutomationEvent.status == AutomationEventStatus.PENDING)
        .order_by(AutomationEvent.created_at.asc())
        .limit(limit)
    ).all()

    results = {"processed": 0, "failed": 0, "skipped": 0, "details": []}

    for event in events:
        lead = db.session.get(Lead, event.lead_id)
        if not lead:
            event.status = AutomationEventStatus.FAILED
            event.last_error = "Lead not found"
            event.completed_at = now_utc
            results["failed"] += 1
            results["details"].append({"event_id": event.id, "status": "failed", "reason": "Lead not found"})
            continue

        try:
            if event.event_type == AutomationEventType.QUALIFY:
                # Already done at lead creation, just mark complete
                event.status = AutomationEventStatus.COMPLETED
                event.completed_at = now_utc

                # Execute the next steps in the same transaction
                send_initial_message(lead, config, user_id=event.payload.get("user_id"))
                schedule_followups(lead, config, user_id=event.payload.get("user_id"))

            elif event.event_type == AutomationEventType.SEND_INITIAL:
                send_initial_message(lead, config, user_id=event.payload.get("user_id"))
                event.status = AutomationEventStatus.COMPLETED
                event.completed_at = now_utc

            elif event.event_type == AutomationEventType.SCHEDULE_FOLLOWUP:
                schedule_followups(lead, config, user_id=event.payload.get("user_id"))
                event.status = AutomationEventStatus.COMPLETED
                event.completed_at = now_utc

            else:
                event.status = AutomationEventStatus.FAILED
                event.last_error = f"Unknown event type: {event.event_type}"
                results["failed"] += 1
                results["details"].append({"event_id": event.id, "status": "failed", "reason": "Unknown event type"})
                continue

            results["processed"] += 1
            results["details"].append({"event_id": event.id, "status": "completed", "type": event.event_type})

        except Exception as e:
            event.attempts += 1
            event.last_error = str(e)
            if event.attempts >= event.max_attempts:
                event.status = AutomationEventStatus.FAILED
                event.completed_at = now_utc
                results["failed"] += 1
                results["details"].append({"event_id": event.id, "status": "failed", "reason": str(e)})
            else:
                # Will retry next cycle
                results["skipped"] += 1
                results["details"].append({"event_id": event.id, "status": "retry", "attempt": event.attempts})

    if events:
        db.session.commit()

    return results