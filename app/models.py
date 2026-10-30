"""Database models for SHA LeadFlow AI."""

from __future__ import annotations

from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db
from .utils import local_today


def utcnow() -> datetime:
    """Naive UTC timestamps, stored consistently across SQLite and PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class User(TimestampMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), nullable=False, unique=True)
    normalized_email = db.Column(db.String(254), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<User {self.id} {self.email}>"


class Lead(TimestampMixin, db.Model):
    __tablename__ = "leads"
    __table_args__ = (
        db.UniqueConstraint("normalized_phone", name="uq_leads_normalized_phone"),
        db.UniqueConstraint("normalized_email", name="uq_leads_normalized_email"),
        db.CheckConstraint("score >= 0 AND score <= 100", name="ck_leads_score_range"),
        db.CheckConstraint(
            "budget_min IS NULL OR budget_min >= 0", name="ck_leads_budget_min_nonnegative"
        ),
        db.CheckConstraint(
            "budget_max IS NULL OR budget_max >= 0", name="ck_leads_budget_max_nonnegative"
        ),
        db.CheckConstraint(
            "budget_min IS NULL OR budget_max IS NULL OR budget_max >= budget_min",
            name="ck_leads_budget_range",
        ),
        db.Index("ix_leads_status_score", "status", "score"),
        db.Index("ix_leads_source", "source"),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    phone = db.Column(db.String(32))
    normalized_phone = db.Column(db.String(20))
    email = db.Column(db.String(254))
    normalized_email = db.Column(db.String(254))
    locality = db.Column(db.String(120), index=True)
    property_type = db.Column(db.String(40))
    project_type = db.Column(db.String(40))
    budget_min = db.Column(db.Integer)
    budget_max = db.Column(db.Integer)
    expected_start = db.Column(db.Date)
    requirements = db.Column(db.Text)
    source = db.Column(db.String(40), nullable=False, default="Other")
    status = db.Column(db.String(30), nullable=False, default="New", index=True)

    score = db.Column(db.Integer, nullable=False, default=0)
    score_factors = db.Column(db.JSON)

    ai_summary = db.Column(db.Text)
    ai_next_action = db.Column(db.String(300))
    ai_extracted = db.Column(db.JSON)
    ai_provider = db.Column(db.String(40))
    ai_updated_at = db.Column(db.DateTime)

    activities = db.relationship(
        "Activity",
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="Activity.created_at.desc()",
        lazy="selectin",
    )
    followups = db.relationship(
        "FollowUp",
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="FollowUp.due_date.asc()",
        lazy="selectin",
    )

    def to_scoring_dict(self) -> dict:
        return {
            "budget_min": self.budget_min,
            "budget_max": self.budget_max,
            "requirements": self.requirements or "",
            "expected_start": self.expected_start,
            "property_type": self.property_type or "",
            "project_type": self.project_type or "",
            "locality": self.locality or "",
            "source": self.source or "Other",
            "status": self.status or "New",
        }

    @property
    def primary_contact(self) -> str:
        return self.phone or self.email or "—"

    @property
    def pending_followups(self) -> list:
        return [item for item in self.followups if item.status == "pending"]

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Lead {self.id} {self.name!r}>"


class Activity(db.Model):
    __tablename__ = "activities"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    kind = db.Column(db.String(40), nullable=False)
    message = db.Column(db.Text, nullable=False)
    details = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    lead = db.relationship("Lead", back_populates="activities")
    user = db.relationship("User")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Activity {self.id} {self.kind}>"


class FollowUp(TimestampMixin, db.Model):
    __tablename__ = "followups"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('pending', 'completed')", name="ck_followups_status"
        ),
        db.Index("ix_followups_due_status", "due_date", "status"),
    )

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(180), nullable=False)
    notes = db.Column(db.Text)
    due_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    completed_at = db.Column(db.DateTime)
    draft_message = db.Column(db.Text)
    draft_provider = db.Column(db.String(40))
    draft_generated_at = db.Column(db.DateTime)

    lead = db.relationship("Lead", back_populates="followups")

    @property
    def is_overdue(self) -> bool:
        return self.status == "pending" and self.due_date < local_today()

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<FollowUp {self.id} due={self.due_date} status={self.status}>"


class AutomationEventStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AutomationEventType:
    QUALIFY = "qualify"
    SEND_INITIAL = "send_initial"
    SCHEDULE_FOLLOWUP = "schedule_followup"


class AutomationEvent(TimestampMixin, db.Model):
    """Transactional outbox record for lead automation events."""

    __tablename__ = "automation_events"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(
        db.Integer, db.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type = db.Column(db.String(40), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default=AutomationEventStatus.PENDING, index=True)
    idempotency_key = db.Column(db.String(120), nullable=False, unique=True, index=True)
    payload = db.Column(db.JSON, nullable=True)
    error = db.Column(db.Text, nullable=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=5)
    next_retry_at = db.Column(db.DateTime, nullable=True, index=True)
    processed_at = db.Column(db.DateTime, nullable=True)

    lead = db.relationship("Lead", backref="automation_events")

    __table_args__ = (
        db.UniqueConstraint(
            "lead_id", "event_type", "idempotency_key", name="uq_automation_event_lead_type_key"
        ),
        db.Index("ix_automation_events_status_next_retry", "status", "next_retry_at"),
    )

    def __repr__(self):  # pragma: no cover - debugging helper
        return f"<AutomationEvent {self.id} {self.event_type} {self.status}>"


class WhatsAppConsent(TimestampMixin, db.Model):
    """WhatsApp opt-in / opt-out consent tracking per lead."""

    __tablename__ = "whatsapp_consents"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(
        db.Integer, db.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    opted_in = db.Column(db.Boolean, nullable=False, default=False)
    consented_at = db.Column(db.DateTime, nullable=True)
    consent_source = db.Column(db.String(80), nullable=True)
    consent_version = db.Column(db.String(40), nullable=True)
    opted_out_at = db.Column(db.DateTime, nullable=True)
    opt_out_reason = db.Column(db.String(120), nullable=True)

    lead = db.relationship("Lead", backref=db.backref("whatsapp_consent", uselist=False))

    def __repr__(self):  # pragma: no cover - debugging helper
        return f"<WhatsAppConsent lead={self.lead_id} opted_in={self.opted_in}>"


class OutboundMessage(TimestampMixin, db.Model):
    """Persisted record of every outbound WhatsApp message attempt."""

    __tablename__ = "outbound_messages"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(
        db.Integer, db.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel = db.Column(db.String(20), nullable=False, default="whatsapp")
    purpose = db.Column(db.String(40), nullable=False, index=True)
    message_type = db.Column(db.String(20), nullable=False)
    template_name = db.Column(db.String(120), nullable=True)
    template_language = db.Column(db.String(20), nullable=True)
    content = db.Column(db.Text, nullable=True)
    provider_message_id = db.Column(db.String(120), nullable=True, index=True)
    idempotency_key = db.Column(db.String(120), nullable=False, unique=True, index=True)
    status = db.Column(db.String(20), nullable=False, index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=5)
    error = db.Column(db.Text, nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)

    lead = db.relationship("Lead", backref="outbound_messages")

    __table_args__ = (
        db.Index("ix_outbound_messages_lead_status", "lead_id", "status"),
        db.Index("ix_outbound_messages_status_created", "status", "created_at"),
    )

    def __repr__(self):  # pragma: no cover - debugging helper
        return f"<OutboundMessage {self.id} {self.purpose} {self.status}>"


class ScheduledJobStatus:
    PENDING = "pending"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScheduledJob(TimestampMixin, db.Model):
    """Persistent job queue for timed follow-ups and automation retries."""

    __tablename__ = "scheduled_jobs"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(
        db.Integer, db.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_type = db.Column(db.String(40), nullable=False, index=True)
    scheduled_at_utc = db.Column(db.DateTime, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default=ScheduledJobStatus.PENDING, index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=5)
    next_retry_at = db.Column(db.DateTime, nullable=True, index=True)
    idempotency_key = db.Column(db.String(120), nullable=False, unique=True, index=True)
    last_error = db.Column(db.Text, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    lead = db.relationship("Lead", backref="scheduled_jobs")

    __table_args__ = (
        db.Index("ix_scheduled_jobs_status_scheduled", "status", "scheduled_at_utc"),
        db.Index("ix_scheduled_jobs_claimed_recovery", "status", "updated_at"),
    )

    def __repr__(self):  # pragma: no cover - debugging helper
        return f"<ScheduledJob {self.id} {self.job_type} {self.status}>"


class InboundMessage(TimestampMixin, db.Model):
    """Persisted record of every inbound WhatsApp webhook message."""

    __tablename__ = "inbound_messages"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(
        db.Integer, db.ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider_message_id = db.Column(db.String(120), nullable=False, unique=True, index=True)
    direction = db.Column(db.String(20), nullable=False, default="inbound")
    content = db.Column(db.Text, nullable=True)
    received_at = db.Column(db.DateTime, nullable=False, index=True)
    processed = db.Column(db.Boolean, nullable=False, default=False)
    opt_out_detected = db.Column(db.Boolean, nullable=False, default=False)
    error = db.Column(db.Text, nullable=True)

    lead = db.relationship("Lead", backref="inbound_messages")

    def __repr__(self):  # pragma: no cover - debugging helper
        return f"<InboundMessage {self.id} provider={self.provider_message_id}>"
