from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func

from app.extensions import db
from app.models import Activity, FollowUp
from app.utils import local_today


def test_create_followup_from_lead(auth_client, make_lead):
    lead = make_lead()
    due = local_today() - timedelta(days=1)
    response = auth_client.post(
        f"/followups/lead/{lead.id}",
        data={"title": "Call about measurements", "due_date": due.isoformat(), "notes": "Fictional note"},
    )
    assert response.status_code == 302
    assert f"/leads/{lead.id}" in response.headers["Location"]

    followup = db.session.scalars(db.select(FollowUp)).one()
    assert followup.title == "Call about measurements"
    assert followup.due_date == due
    assert followup.status == "pending"
    assert followup.is_overdue
    assert any(activity.kind == "followup_created" for activity in lead.activities)


def test_overdue_followup_appears_on_dashboard(auth_client, make_lead):
    lead = make_lead(name="Reminder Fictional")
    followup = FollowUp(
        lead=lead,
        title="Overdue dashboard task",
        due_date=local_today() - timedelta(days=2),
    )
    db.session.add(followup)
    db.session.commit()

    response = auth_client.get("/")
    assert response.status_code == 200
    assert b"Overdue dashboard task" in response.data
    assert b"Overdue" in response.data


def test_complete_and_reopen_followup(auth_client, make_lead):
    lead = make_lead()
    followup = FollowUp(
        lead=lead,
        title="Close the loop",
        due_date=local_today(),
    )
    db.session.add(followup)
    db.session.commit()

    response = auth_client.post(
        f"/followups/{followup.id}/complete", data={"return_to": "lead"}
    )
    assert response.status_code == 302
    db.session.refresh(followup)
    assert followup.status == "completed"
    assert followup.completed_at is not None
    assert any(
        activity.kind == "followup_completed" for activity in lead.activities
    )

    response = auth_client.post(
        f"/followups/{followup.id}/reopen", data={"return_to": "followups"}
    )
    assert response.status_code == 302
    db.session.refresh(followup)
    assert followup.status == "pending"
    assert followup.completed_at is None


def test_followup_validation_rejects_empty_payload(auth_client, make_lead):
    lead = make_lead()
    response = auth_client.post(f"/followups/lead/{lead.id}", data={})
    assert response.status_code == 302
    assert db.session.scalar(db.select(func.count(FollowUp.id))) == 0
    assert db.session.scalar(db.select(func.count(Activity.id)))


def test_draft_falls_back_without_ai(auth_client, make_lead):
    lead = make_lead(name="Meera Fictional")
    followup = FollowUp(
        lead=lead,
        title="Confirm site visit",
        due_date=local_today() + timedelta(days=2),
    )
    db.session.add(followup)
    db.session.commit()

    response = auth_client.post(f"/followups/{followup.id}/draft")
    assert response.status_code == 302
    db.session.refresh(followup)
    assert followup.draft_provider == "fallback"
    assert followup.draft_message
    assert "Meera" in followup.draft_message
    assert "Draft" not in followup.draft_message  # it is a message, not a UI label
    assert any(activity.kind == "message_drafted" for activity in lead.activities)


def test_followup_queue_views(auth_client, make_lead):
    lead = make_lead()
    overdue = FollowUp(
        lead=lead, title="Late task", due_date=local_today() - timedelta(days=1)
    )
    upcoming = FollowUp(
        lead=lead, title="Later task", due_date=local_today() + timedelta(days=3)
    )
    completed = FollowUp(
        lead=lead,
        title="Done task",
        due_date=local_today() - timedelta(days=2),
        status="completed",
    )
    db.session.add_all([overdue, upcoming, completed])
    db.session.commit()

    response = auth_client.get("/followups/?view=overdue")
    text = response.get_data(as_text=True)
    assert "Late task" in text
    assert "Later task" not in text

    response = auth_client.get("/followups/?view=completed")
    text = response.get_data(as_text=True)
    assert "Done task" in text
    assert "Late task" not in text

    response = auth_client.get("/followups/?view=all")
    text = response.get_data(as_text=True)
    assert "Late task" in text and "Done task" in text
