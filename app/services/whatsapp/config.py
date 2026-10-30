"""WhatsApp Cloud API configuration."""
from __future__ import annotations

import os


class WhatsAppConfig:
    """WhatsApp configuration from environment variables."""

    def __init__(self):
        self.enabled = os.environ.get("WHATSAPP_ENABLED", "false").lower() == "true"
        self.phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
        self.access_token = os.environ.get("WHATSAPP_ACCESS_TOKEN", "").strip()
        self.api_version = os.environ.get("WHATSAPP_API_VERSION", "v20.0").strip()
        self.verify_token = os.environ.get("WHATSAPP_VERIFY_TOKEN", "").strip()
        self.app_secret = os.environ.get("WHATSAPP_APP_SECRET", "").strip()
        self.default_template = os.environ.get("WHATSAPP_DEFAULT_TEMPLATE", "").strip()
        self.default_template_language = os.environ.get("WHATSAPP_DEFAULT_TEMPLATE_LANGUAGE", "en_US").strip()
        self.dry_run = os.environ.get("WHATSAPP_DRY_RUN", "true").lower() == "true"
        self.max_messages_per_run = int(os.environ.get("WHATSAPP_MAX_MESSAGES_PER_RUN", "50"))

    @property
    def base_url(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}"

    @property
    def messages_url(self) -> str:
        return f"{self.base_url}/{self.phone_number_id}/messages"

    def is_configured(self) -> bool:
        return bool(
            self.enabled
            and self.phone_number_id
            and self.access_token
        )


# Singleton instance
whatsapp_config = WhatsAppConfig()