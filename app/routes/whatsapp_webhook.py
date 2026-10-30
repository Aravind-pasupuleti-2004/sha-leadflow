"""WhatsApp webhook routes for inbound messages and status updates."""

from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, request

from ..services.whatsapp import whatsapp_config
from ..services.whatsapp.webhook import process_inbound_message
from ..services.whatsapp.provider import WhatsAppProvider

logger = logging.getLogger(__name__)

bp = Blueprint("whatsapp_webhook", __name__, url_prefix="/webhook")


def _verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify X-Hub-Signature-256 from Meta."""
    if not whatsapp_config.app_secret:
        return False
    provider = WhatsAppProvider(whatsapp_config)
    return provider.verify_webhook_signature(payload, signature)


@bp.get("/whatsapp")
def verify_webhook():
    """Verify webhook subscription with Meta."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == whatsapp_config.verify_token:
        logger.info("Webhook verified successfully")
        return challenge, 200

    logger.warning("Webhook verification failed: mode=%s, token_match=%s", mode, token == whatsapp_config.verify_token)
    return "Forbidden", 403


@bp.post("/whatsapp")
def receive_webhook():
    """Receive inbound WhatsApp messages and status updates."""
    # Verify signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    if whatsapp_config.app_secret and not _verify_webhook_signature(request.get_data(), signature):
        logger.warning("Invalid webhook signature")
        return "Invalid signature", 403

    try:
        payload = request.get_json(force=True)
    except Exception as e:
        logger.error("Invalid JSON payload: %s", e)
        return "Bad Request", 400

    if not payload:
        return "Bad Request", 400

    logger.info("Received webhook: %s", payload.get("entry", [{}])[0].get("changes", [{}])[0].get("field", "unknown"))

    result = process_inbound_message(payload)

    return jsonify(result), 200