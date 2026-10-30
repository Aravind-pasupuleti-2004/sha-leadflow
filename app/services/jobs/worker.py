"""Persistent job queue worker for timed follow-ups and automation retries.

Uses SELECT ... FOR UPDATE SKIP LOCKED to safely claim jobs.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, update

from ...extensions import db
from ...models import (
    Lead,
    ScheduledJob,
    ScheduledJobStatus,
)
from ..ai import build_provider, generate_followup_draft
from ..whatsapp import send_message
from ...config import Config


def get_due_jobs(limit: int = 50) -> list[ScheduledJob]:
    """Get jobs that are due for processing.

    Uses SELECT ... FOR UPDATE SKIP LOCKED to safely claim jobs.
    """
    now_utc = datetime.now(timezone.utc)

    stmt = (
        select(ScheduledJob)
        .where(
            ScheduledJob.status == ScheduledJobStatus.PENDING,
            ScheduledJob.scheduled_at_utc <= now_utc,
        )
        .order_by(ScheduledJob.scheduled_at_utc.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    jobs = db.session.scalars(stmt).all()

    # Mark as claimed
    for job in jobs:
        job.status = ScheduledJobStatus.CLAIMED
        job.attempts += 1

    if jobs:
        db.session.commit()

    return jobs


def _can_send_to_lead(lead: Lead) -> bool:
    """Check if a lead is eligible to receive automated messages."""
    # Must have valid phone
    if not lead.normalized_phone:
        return False

    # Must have WhatsApp consent
    consent = lead.whatsapp_consent
    if not consent or not consent.opted_in:
        return False
    if consent.opted_out_at:
        return False

    # Lead must not be in terminal state
    if lead.status in ("Won", "Lost"):
        return False

    return True


def process_job(job: ScheduledJob, config: dict) -> bool:
    """Process a single scheduled job.

    Returns True if successful, False if should retry later.
    """
    lead = db.session.get(Lead, job.lead_id)
    if not lead:
        job.status = ScheduledJobStatus.CANCELLED
        job.last_error = "Lead not found"
        job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()
        return True  # Don't retry - lead gone

    # Revalidate before sending
    if not _can_send_to_lead(lead):
        job.status = ScheduledJobStatus.CANCELLED
        job.last_error = "Lead ineligible for messaging"
        job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()
        return True

    try:
        # Generate follow-up draft
        from datetime import date
        # Create a temporary followup-like object for draft generation
        class _TempFollowup:
            due_date = date.today()

        draft_result = generate_followup_draft(
            lead,
            _TempFollowup(),
            config,
            provider=build_provider(config),
        )

        # Send via WhatsApp
        send_result = send_message(
            lead=lead,
            content=draft_result.message,
            purpose=f"followup_{job.job_type}",
            message_type="text",
            idempotency_key=f"{job.idempotency_key}:{job.attempts}",
        )

        job.status = ScheduledJobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()
        return True

    except Exception as e:
        job.last_error = str(e)
        job.next_retry_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
            minutes=min(30 * (2 ** job.attempts), 240)
        )
        if job.attempts >= job.max_attempts:
            job.status = ScheduledJobStatus.FAILED
            job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()
        return False


def cancel_pending_jobs(lead_id: int, reason: str = "cancelled") -> int:
    """Cancel all pending/claimed jobs for a lead."""
    stmt = (
        update(ScheduledJob)
        .where(
            ScheduledJob.lead_id == lead_id,
            ScheduledJob.status.in_([ScheduledJobStatus.PENDING, ScheduledJobStatus.CLAIMED]),
        )
        .values(status=ScheduledJobStatus.CANCELLED, last_error=reason)
    )
    result = db.session.execute(stmt)
    db.session.commit()
    return result.rowcount


def pause_automation(lead_id: int, user_id: Optional[int] = None) -> bool:
    """Pause all automation for a lead (admin action)."""
    lead = db.session.get(Lead, lead_id)
    if not lead:
        return False

    cancel_pending_jobs(lead_id, "automation_paused")

    from ..models import Activity
    activity = Activity(
        lead=lead,
        user_id=user_id,
        kind="automation_paused",
        message="Automation paused by administrator",
    )
    db.session.add(activity)
    db.session.commit()
    return True


def resume_automation(lead_id: int, user_id: Optional[int] = None) -> bool:
    """Resume automation for a lead (admin action)."""
    lead = db.session.get(Lead, lead_id)
    if not lead:
        return False

    # Re-schedule followups if consented
    from ..services.automation import schedule_followups
    config = Config()
    schedule_followups(lead, config, user_id)

    from ..models import Activity
    activity = Activity(
        lead=lead,
        user_id=user_id,
        kind="automation_resumed",
        message="Automation resumed by administrator",
    )
    db.session.add(activity)
    db.session.commit()
    return True


__all__ = [
    "get_due_jobs",
    "process_job",
    "cancel_pending_jobs",
    "pause_automation",
    "resume_automation",
]