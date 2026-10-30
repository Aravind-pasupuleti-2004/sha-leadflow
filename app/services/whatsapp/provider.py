"""WhatsApp Cloud API provider adapter.

Isolated from Flask route handlers. Uses server-side environment variables.
"""
from __future__ import annotations

import hmac
import hashlib
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from ...extensions import db
from ...models import OutboundMessage, WhatsAppConsent
from .config import whatsapp_config


@dataclass
class SendResult:
    """Result of a WhatsApp send attempt."""
    success: bool
    provider_message_id: Optional[str] = None
    error: Optional[str] = None
    status: str = "failed"


class WhatsAppProvider:
    """WhatsApp Business Platform Cloud API adapter."""

    def __init__(self, config=None):
        self.config = config or whatsapp_config
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.config.access_token}",
            "Content-Type": "application/json",
        })

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """Verify X-Hub-Signature-256 from Meta."""
        if not self.config.app_secret:
            return False
        expected = "sha256=" + hmac.new(
            self.config.app_secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def send_text_message(
        self,
        to: str,
        body: str,
        preview_url: bool = False,
    ) -> SendResult:
        """Send a free-form text message (session messages only)."""
        if self.config.dry_run:
            return SendResult(
                success=True,
                provider_message_id=f"dryrun_{uuid.uuid4().hex[:12]}",
                status="sent",
            )

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"preview_url": preview_url, "body": body},
        }
        return self._post(payload)

    def send_template_message(
        self,
        to: str,
        template_name: str,
        language_code: str,
        components: list[dict] | None = None,
    ) -> SendResult:
        """Send a template message (for non-session or approved templates)."""
        if self.config.dry_run:
            return SendResult(
                success=True,
                provider_message_id=f"dryrun_{uuid.uuid4().hex[:12]}",
                status="sent",
            )

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
            },
        }
        if components:
            payload["template"]["components"] = components

        return self._post(payload)

    def _post(self, payload: dict) -> SendResult:
        """POST to Graph API with error handling."""
        url = self.config.messages_url
        try:
            response = self._session.post(url, json=payload, timeout=30)
        except requests.Timeout:
            return SendResult(success=False, error="Request timeout", status="failed")
        except requests.RequestException as e:
            return SendResult(success=False, error=f"Network error: {e}", status="failed")

        if response.status_code >= 200 and response.status_code < 300:
            data = response.json()
            msg_id = data.get("messages", [{}])[0].get("id")
            return SendResult(
                success=True,
                provider_message_id=msg_id,
                status="sent",
            )

        # Parse error response
        error_msg = f"HTTP {response.status_code}"
        try:
            err_data = response.json()
            if "error" in err_data:
                error_msg = err_data["error"].get("message", error_msg)
        except Exception:
            error_msg = response.text[:200] or error_msg

        return SendResult(success=False, error=error_msg, status="failed")


def send_message(
    lead,
    content: str,
    purpose: str,
    message_type: str = "text",
    template_name: str | None = None,
    template_language: str | None = None,
    template_components: list[dict] | None = None,
    idempotency_key: str | None = None,
) -> SendResult:
    """
    Send a WhatsApp message for a lead.

    Args:
        lead: Lead model instance
        content: Message body (for text messages)
        purpose: Purpose of message (e.g., "initial", "followup_1d", "followup_3d")
        message_type: "text" or "template"
        template_name: Template name (required if message_type="template")
        template_language: Template language code (e.g., "en_US")
        template_components: Template variable components
        idempotency_key: Unique key to prevent duplicate sends

    Returns:
        SendResult with success status and provider message ID
    """
    # Generate idempotency key if not provided
    if not idempotency_key:
        idempotency_key = f"{lead.id}:{purpose}:{int(time.time())}"

    # Check for existing message with same idempotency key
    existing = db.session.scalars(
        db.select(OutboundMessage).where(OutboundMessage.idempotency_key == idempotency_key)
    ).first()
    if existing:
        return SendResult(
            success=True,
            provider_message_id=existing.provider_message_id,
            status=existing.status,
        )

    # Check consent
    consent = lead.whatsapp_consent
    if not consent or not consent.opted_in:
        result = SendResult(success=False, error="WhatsApp consent not granted", status="failed")
        _record_outbound(lead, content, purpose, message_type, idempotency_key, result)
        return result

    if consent.opted_out_at:
        result = SendResult(success=False, error="User opted out", status="failed")
        _record_outbound(lead, content, purpose, message_type, idempotency_key, result)
        return result

    # Validate phone
    if not lead.normalized_phone:
        result = SendResult(success=False, error="No phone number", status="failed")
        _record_outbound(lead, content, purpose, message_type, idempotency_key, result)
        return result

    # Initialize provider
    provider = WhatsAppProvider()

    # Send based on message type
    if message_type == "template":
        if not template_name:
            result = SendResult(success=False, error="Template name required", status="failed")
            _record_outbound(lead, content, purpose, message_type, idempotency_key, result)
            return result
        send_result = provider.send_template_message(
            to=lead.normalized_phone,
            template_name=template_name,
            language_code=template_language or whatsapp_config.default_template_language,
            components=template_components,
        )
    else:
        send_result = provider.send_text_message(
            to=lead.normalized_phone,
            body=content,
        )

    # Record the outbound message
    _record_outbound(lead, content, purpose, message_type, idempotency_key, send_result)

    return send_result


def _record_outbound(
    lead,
    content: str,
    purpose: str,
    message_type: str,
    idempotency_key: str,
    result: SendResult,
) -> OutboundMessage:
    """Record outbound message attempt in database."""
    outbound = OutboundMessage(
        lead_id=lead.id,
        content=content,
        purpose=purpose,
        message_type=message_type,
        provider_message_id=result.provider_message_id,
        idempotency_key=idempotency_key,
        status=result.status if result.success else "failed",
        attempts=1,
        max_attempts=3,
        error=result.error,
        sent_at=datetime.now(timezone.utc).replace(tzinfo=None) if result.success else None,
    )
    db.session.add(outbound)
    db.session.commit()
    return outbound


def retry_failed_messages(max_retries: int = 3) -> int:
    """Retry failed outbound messages that haven't exceeded max attempts."""
    failed = db.session.scalars(
        db.select(OutboundMessage).where(
            OutboundMessage.status == "failed",
            OutboundMessage.attempts < OutboundMessage.max_attempts,
        )
    ).all()

    retried = 0
    provider = WhatsAppProvider()
    for msg in failed:
        lead = db.session.get(msg.lead_id)
        if not lead or not lead.normalized_phone:
            continue

        if msg.message_type == "template":
            send_result = provider.send_template_message(
                to=lead.normalized_phone,
                template_name=msg.content,
                language_code=msg.purpose,
                components=[],
            )
        else:
            send_result = provider.send_text_message(
                to=lead.normalized_phone,
                body=msg.content,
            )

        msg.attempts += 1
        if send_result.success:
            msg.status = send_result.status
            msg.provider_message_id = send_result.provider_message_id
            msg.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
            msg.error = None
        else:
            msg.error = send_result.error
            if msg.attempts >= msg.max_attempts:
                msg.status = "failed"

        db.session.add(msg)
        retried += 1

    if retried:
        db.session.commit()
    return retried