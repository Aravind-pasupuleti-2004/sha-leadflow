"""Tests for the automation engine."""

from __future__ import annotations

import pytest
from datetime import date, datetime, timedelta, timezone

from app.models import (
    Lead,
    AutomationEvent,
    AutomationEventType,
    ScheduledJob,
    OutboundMessage,
    WhatsAppConsent,
    Activity,
    InboundMessage,
)
from app.services.leads import create_lead
from app.services.validation import normalize_phone, normalize_email
from app.services.automation import (
    process_pending_automation_events,
    send_initial_message,
    schedule_followups,
)
from app.services.jobs import get_due_jobs, process_job
from app.services.whatsapp import send_message, retry_failed_messages
from app.services.whatsapp.webhook import process_inbound_message


@pytest.fixture
def sample_lead_data():
    """Sample lead data for testing."""
    return {
        "name": "Test Customer",
        "phone": "9000000001",
        "email": "test@example.com",
        "locality": "Indiranagar",
        "property_type": "Apartment",
        "project_type": "Full Home Interiors",
        "budget_min": 800000,
        "budget_max": 1200000,
        "expected_start": date(2026, 12, 15),
        "requirements": "3BHK apartment, modern luxury interiors, modular kitchen",
        "source": "Website",
        "status": "New",
        "normalized_phone": normalize_phone("9000000001"),
        "normalized_email": normalize_email("test@example.com"),
    }


@pytest.fixture
def app_with_auto_opt_in(app):
    """App with auto opt-in enabled for testing."""
    app.config["AUTOMATION_AUTO_OPT_IN"] = True
    app.config["AUTOMATION_INITIAL_ENABLED"] = True
    return app


def test_lead_creation_triggers_automation(app_with_auto_opt_in, sample_lead_data):
    """Test that creating a lead triggers the automation pipeline."""
    with app_with_auto_opt_in.app_context():
        lead = create_lead(sample_lead_data, app_with_auto_opt_in.config, user_id=1)
        from app.extensions import db
        db.session.commit()

        events = AutomationEvent.query.filter_by(lead_id=lead.id).all()
        assert len(events) == 1
        assert events[0].event_type == AutomationEventType.QUALIFY
        assert events[0].status == "pending"


def test_automation_pipeline_executes_fully(app_with_auto_opt_in, sample_lead_data):
    """Test the full automation pipeline: qualify -> send_initial -> schedule_followup."""
    with app_with_auto_opt_in.app_context():
        lead = create_lead(sample_lead_data, app_with_auto_opt_in.config, user_id=1)
        from app.extensions import db
        db.session.commit()

        result = process_pending_automation_events(app_with_auto_opt_in.config, limit=50)

        # QUALIFY event processed, which triggers send_initial and schedule_followup
        assert result["processed"] >= 1
        assert result["failed"] == 0

        events = AutomationEvent.query.filter_by(lead_id=lead.id).all()
        for event in events:
            assert event.status == "completed"

        outbound = OutboundMessage.query.filter_by(lead_id=lead.id, purpose="initial").first()
        assert outbound is not None
        assert outbound.status == "sent"
        assert "dryrun" in outbound.provider_message_id

        jobs = ScheduledJob.query.filter_by(lead_id=lead.id).all()
        assert len(jobs) == 3
        job_types = {j.job_type for j in jobs}
        assert job_types == {"followup_1d", "followup_3d", "followup_7d"}

        activities = Activity.query.filter_by(lead_id=lead.id).all()
        activity_kinds = {a.kind for a in activities}
        assert "created" in activity_kinds
        assert "qualified" in activity_kinds
        assert "initial_message_sent" in activity_kinds
        assert "followups_scheduled" in activity_kinds


def test_personalized_initial_message_content(app_with_auto_opt_in, sample_lead_data):
    """Test that initial message is personalized with lead details."""
    with app_with_auto_opt_in.app_context():
        lead = create_lead(sample_lead_data, app_with_auto_opt_in.config, user_id=1)
        from app.extensions import db
        db.session.commit()

        process_pending_automation_events(app_with_auto_opt_in.config, limit=50)

        outbound = OutboundMessage.query.filter_by(lead_id=lead.id, purpose="initial").first()
        content = outbound.content

        assert "Test Customer" in content or "Test" in content
        assert "Indiranagar" in content
        assert "Full Home Interiors" in content or "full home interiors" in content.lower()
        assert "3BHK" in content or "apartment" in content.lower()
        assert "modular kitchen" in content.lower()


def test_different_leads_get_different_messages(app_with_auto_opt_in):
    """Test that different leads receive different personalized messages."""
    with app_with_auto_opt_in.app_context():
        lead1_data = {
            "name": "Rahul Sharma",
            "phone": "9000000001",
            "email": "rahul@example.com",
            "locality": "Kokapet",
            "property_type": "Apartment",
            "project_type": "Full Home Interiors",
            "budget_min": 2500000,
            "budget_max": 3500000,
            "expected_start": date(2026, 11, 15),
            "requirements": "3BHK apartment, modern luxury interiors, modular kitchen and premium bedroom designs",
            "source": "Website",
            "status": "New",
            "normalized_phone": normalize_phone("9000000001"),
            "normalized_email": normalize_email("rahul@example.com"),
        }

        lead2_data = {
            "name": "Priya Patel",
            "phone": "9000000002",
            "email": "priya@example.com",
            "locality": "Whitefield",
            "property_type": "Office",
            "project_type": "Renovation",
            "budget_min": 5000000,
            "budget_max": 8000000,
            "expected_start": date(2026, 12, 1),
            "requirements": "Commercial office renovation, modern workspace design, collaborative spaces",
            "source": "Website",
            "status": "New",
            "normalized_phone": normalize_phone("9000000002"),
            "normalized_email": normalize_email("priya@example.com"),
        }

        from app.extensions import db

        lead1 = create_lead(lead1_data, app_with_auto_opt_in.config, user_id=1)
        lead2 = create_lead(lead2_data, app_with_auto_opt_in.config, user_id=1)
        db.session.commit()

        process_pending_automation_events(app_with_auto_opt_in.config, limit=50)

        msg1 = OutboundMessage.query.filter_by(lead_id=lead1.id, purpose="initial").first()
        msg2 = OutboundMessage.query.filter_by(lead_id=lead2.id, purpose="initial").first()

        assert msg1 is not None
        assert msg2 is not None
        assert msg1.content != msg2.content

        assert "Rahul" in msg1.content or "Sharma" in msg1.content
        assert "Kokapet" in msg1.content
        assert "3BHK" in msg1.content or "apartment" in msg1.content.lower()
        assert "modular kitchen" in msg1.content.lower()
        assert "bedroom" in msg1.content.lower()

        assert "Priya" in msg2.content or "Patel" in msg2.content
        assert "Whitefield" in msg2.content
        assert "office" in msg2.content.lower() or "commercial" in msg2.content.lower()
        assert "renovation" in msg2.content.lower()


def test_opt_out_cancels_scheduled_jobs(app_with_auto_opt_in, sample_lead_data):
    """Test that customer opt-out cancels pending follow-up jobs."""
    with app_with_auto_opt_in.app_context():
        lead = create_lead(sample_lead_data, app_with_auto_opt_in.config, user_id=1)
        from app.extensions import db
        db.session.commit()

        process_pending_automation_events(app_with_auto_opt_in.config, limit=50)

        jobs_before = ScheduledJob.query.filter_by(lead_id=lead.id).all()
        assert len(jobs_before) == 3
        assert all(j.status == "pending" for j in jobs_before)

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "id": "wamid.stop123",
                            "from": "919000000001",
                            "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                            "type": "text",
                            "text": {"body": "STOP"}
                        }],
                        "contacts": [{"wa_id": "919000000001"}]
                    },
                    "field": "messages"
                }]
            }]
        }

        result = process_inbound_message(payload)
        assert result["messages"][0]["opt_out_detected"] is True

        lead = db.session.get(Lead, lead.id)
        assert lead.whatsapp_consent.opted_in is False
        assert lead.whatsapp_consent.opted_out_at is not None

        jobs_after = ScheduledJob.query.filter_by(lead_id=lead.id).all()
        assert all(j.status == "cancelled" for j in jobs_after)


def test_inbound_message_processing(app_with_auto_opt_in, sample_lead_data):
    """Test that inbound messages are processed and stored."""
    with app_with_auto_opt_in.app_context():
        lead = create_lead(sample_lead_data, app_with_auto_opt_in.config, user_id=1)
        from app.extensions import db
        db.session.commit()

        process_pending_automation_events(app_with_auto_opt_in.config, limit=50)

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "id": "wamid.reply123",
                            "from": "919000000001",
                            "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                            "type": "text",
                            "text": {"body": "Yes, I'm interested. When can we meet?"}
                        }],
                        "contacts": [{"wa_id": "919000000001"}]
                    },
                    "field": "messages"
                }]
            }]
        }

        result = process_inbound_message(payload)
        assert result["messages"][0]["status"] == "processed"
        assert result["messages"][0]["lead_id"] == lead.id

        from app.models import InboundMessage
        inbound = db.session.query(InboundMessage).filter_by(provider_message_id="wamid.reply123").first()
        assert inbound is not None
        assert inbound.lead_id == lead.id
        assert "interested" in inbound.content
        assert inbound.processed is True


def test_followup_job_processing(app_with_auto_opt_in, sample_lead_data):
    """Test that follow-up jobs are processed when due."""
    with app_with_auto_opt_in.app_context():
        lead = create_lead(sample_lead_data, app_with_auto_opt_in.config, user_id=1)
        from app.extensions import db
        db.session.commit()

        process_pending_automation_events(app_with_auto_opt_in.config, limit=50)

        job = ScheduledJob.query.filter_by(lead_id=lead.id, job_type="followup_1d").first()
        job.scheduled_at_utc = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.session.commit()

        due_jobs = get_due_jobs(limit=10)
        assert len(due_jobs) >= 1

        for j in due_jobs:
            if j.id == job.id:
                success = process_job(j, app_with_auto_opt_in.config)
                assert success is True

        job = db.session.get(ScheduledJob, job.id)
        assert job.status == "completed"

        followup_msg = OutboundMessage.query.filter_by(
            lead_id=lead.id, purpose="followup_followup_1d"
        ).first()
        assert followup_msg is not None
        assert followup_msg.status == "sent"


def test_duplicate_message_prevention(app_with_auto_opt_in, sample_lead_data):
    """Test that idempotency prevents duplicate messages."""
    with app_with_auto_opt_in.app_context():
        lead = create_lead(sample_lead_data, app_with_auto_opt_in.config, user_id=1)
        from app.extensions import db
        db.session.commit()

        result1 = send_message(
            lead=lead,
            content="Test message",
            purpose="initial",
            message_type="text",
            idempotency_key=f"{lead.id}:initial:test",
        )
        result2 = send_message(
            lead=lead,
            content="Test message 2",
            purpose="initial",
            message_type="text",
            idempotency_key=f"{lead.id}:initial:test",
        )

        assert result1.success is True
        assert result2.success is True
        assert result1.provider_message_id == result2.provider_message_id

        messages = OutboundMessage.query.filter_by(idempotency_key=f"{lead.id}:initial:test").all()
        assert len(messages) == 1


def test_whatsapp_consent_required(app_with_auto_opt_in, sample_lead_data):
    """Test that messages are not sent without consent (but failure is recorded)."""
    with app_with_auto_opt_in.app_context():
        app_with_auto_opt_in.config["AUTOMATION_AUTO_OPT_IN"] = False

        lead = create_lead(sample_lead_data, app_with_auto_opt_in.config, user_id=1)
        from app.extensions import db
        db.session.commit()

        assert lead.whatsapp_consent is not None
        assert lead.whatsapp_consent.opted_in is False

        result = send_message(
            lead=lead,
            content="Test message",
            purpose="initial",
            message_type="text",
        )

        assert result.success is False
        assert "consent" in result.error.lower()

        # Message attempt is recorded for audit trail
        messages = OutboundMessage.query.filter_by(lead_id=lead.id).all()
        assert len(messages) == 1
        assert messages[0].status == "failed"
        assert "consent" in messages[0].error.lower()


def test_worker_restart_persists_jobs(app_with_auto_opt_in, sample_lead_data):
    """Test that scheduled jobs persist across worker/app restarts (simulated by new session)."""
    with app_with_auto_opt_in.app_context():
        lead = create_lead(sample_lead_data, app_with_auto_opt_in.config, user_id=1)
        from app.extensions import db
        db.session.commit()

        process_pending_automation_events(app_with_auto_opt_in.config, limit=50)

        jobs_before = ScheduledJob.query.filter_by(lead_id=lead.id).all()
        assert len(jobs_before) == 3
        job_ids = {j.id for j in jobs_before}

        # Simulate restart by expiring all objects and creating new session
        db.session.expire_all()
        # In a real restart, a new process would connect to the same database
        # Here we just verify the data is committed and queryable
        jobs_after = ScheduledJob.query.filter_by(lead_id=lead.id).all()
        assert len(jobs_after) == 3
        job_ids_after = {j.id for j in jobs_after}
        assert job_ids == job_ids_after