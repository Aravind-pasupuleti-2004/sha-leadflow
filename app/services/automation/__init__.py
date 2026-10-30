"""Automation service package."""
from .service import (
    enqueue_automation,
    qualify_new_lead,
    schedule_followups,
    send_initial_message,
    process_pending_automation_events,
)

__all__ = [
    "enqueue_automation",
    "qualify_new_lead",
    "schedule_followups",
    "send_initial_message",
    "process_pending_automation_events",
]