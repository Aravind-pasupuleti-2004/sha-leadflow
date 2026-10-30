"""Follow-up task creation, completion, and draft storage."""

from __future__ import annotations

from datetime import date

from ..extensions import db
from ..models import FollowUp, utcnow
from .leads import log_activity
from .validation import clean_text_checked


def validate_followup_input(raw) -> tuple[dict, dict]:
    errors: dict[str, str] = {}
    title = clean_text_checked(raw.get("title"), 180, "title", "Follow-up title", errors)
    if len(title) < 3 and "title" not in errors:
        errors["title"] = "Enter a short follow-up title (at least 3 characters)."
    notes = clean_text_checked(raw.get("notes"), 1000, "notes", "Notes", errors)

    due_raw = str(raw.get("due_date") or "").strip()
    due_date = None
    if not due_raw:
        errors["due_date"] = "Choose a due date."
    else:
        try:
            due_date = date.fromisoformat(due_raw)
        except ValueError:
            errors["due_date"] = "Enter a valid due date."
    return {"title": title, "notes": notes or None, "due_date": due_date}, errors


def create_followup(lead, data: dict, user_id: int | None = None, commit: bool = True) -> FollowUp:
    followup = FollowUp(
        lead=lead,
        title=data["title"],
        notes=data["notes"],
        due_date=data["due_date"],
    )
    db.session.add(followup)
    log_activity(
        lead,
        "followup_created",
        f"Follow-up created: {followup.title} (due {followup.due_date.isoformat()}).",
        user_id=user_id,
    )
    if commit:
        db.session.commit()
    return followup


def complete_followup(followup: FollowUp, user_id: int | None = None, commit: bool = True) -> None:
    if followup.status == "completed":
        return
    followup.status = "completed"
    followup.completed_at = utcnow()
    log_activity(
        followup.lead,
        "followup_completed",
        f"Follow-up completed: {followup.title}.",
        user_id=user_id,
    )
    if commit:
        db.session.commit()


def reopen_followup(followup: FollowUp, user_id: int | None = None, commit: bool = True) -> None:
    if followup.status == "pending":
        return
    followup.status = "pending"
    followup.completed_at = None
    log_activity(
        followup.lead,
        "followup_reopened",
        f"Follow-up reopened: {followup.title}.",
        user_id=user_id,
    )
    if commit:
        db.session.commit()


def save_draft(followup: FollowUp, result, user_id: int | None = None, commit: bool = True) -> None:
    followup.draft_message = result.message
    followup.draft_provider = result.provider
    followup.draft_generated_at = utcnow()
    note = (
        f"Message draft generated via {result.provider_label}."
        if not result.fallback
        else "AI unavailable; rule-based message draft generated."
    )
    log_activity(followup.lead, "message_drafted", note, user_id=user_id)
    if commit:
        db.session.commit()
