from __future__ import annotations

from datetime import date, timedelta

from app.models import FollowUp
from app.services.dashboard import build_dashboard

TODAY = date(2026, 10, 29)


def test_dashboard_aggregates_status_source_and_conversion(app, make_lead, make_followup):
    high = make_lead(
        name="High Fit",
        status="New",
        source="Instagram",
        budget_min=1200000,
        budget_max=1800000,
        expected_start=TODAY + timedelta(days=12),
    )
    contacted = make_lead(name="Contacted Lead", status="Contacted", source="Website")
    won = make_lead(name="Won Lead", status="Won", source="Referral")
    lost = make_lead(name="Lost Lead", status="Lost", source="Website")

    make_followup(high, title="Overdue task", due_date=TODAY - timedelta(days=2))
    make_followup(high, title="Today task", due_date=TODAY)
    make_followup(contacted, title="Upcoming task", due_date=TODAY + timedelta(days=3))
    completed = make_followup(won, title="Finished task", due_date=TODAY - timedelta(days=1))
    completed.status = "completed"
    from app.extensions import db

    db.session.commit()

    data = build_dashboard(app.config, today=TODAY)
    assert data["total"] == 4
    assert data["active"] == 2
    assert data["won"] == 1
    assert data["lost"] == 1
    assert data["win_rate"] == 50
    assert data["status_counts"]["New"] == 1
    assert data["status_counts"]["Won"] == 1
    assert data["source_counts"]["Website"] == 2
    assert {item["source"] for item in data["sources"]} == {
        "Website",
        "Instagram",
        "Referral",
    }
    assert len(data["overdue"]) == 1
    assert len(data["due_today"]) == 1
    assert len(data["upcoming"]) == 1
    assert data["open_followups"] == 3
    assert data["completed_followups"] == 1
    assert data["overdue_count"] == 1
    assert data["due_today_count"] == 1
    assert data["upcoming_count"] == 1

    high_names = [lead.name for lead in data["high_priority"]]
    assert "High Fit" in high_names or high.score >= data["threshold"]
    assert "Won Lead" not in high_names
    assert "Lost Lead" not in high_names


def test_dashboard_excludes_won_and_lost_from_priority(app, make_lead):
    make_lead(name="Won Priority", status="Won", budget_max=3000000)
    make_lead(name="Lost Priority", status="Lost", budget_max=3000000)
    active = make_lead(
        name="Active Priority",
        status="Qualified",
        budget_max=3000000,
        locality="Indiranagar",
        project_type="Full Home Interiors",
        expected_start=TODAY + timedelta(days=10),
        requirements="Ready to finalise and book a site visit. Budget approved.",
    )
    data = build_dashboard(app.config, today=TODAY)
    names = [lead.name for lead in data["high_priority"]]
    assert active.name in names
    assert "Won Priority" not in names
    assert "Lost Priority" not in names


def test_dashboard_route_renders(auth_client, make_lead):
    make_lead(name="Visible Lead", status="New")
    response = auth_client.get("/")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Pipeline overview" in text
    assert "Lead sources" in text
    assert "Follow-up queue" in text


def test_dashboard_conversion_with_no_decided_leads(app, make_lead):
    make_lead(status="New")
    data = build_dashboard(app.config, today=TODAY)
    assert data["win_rate"] == 0
    assert data["active"] == 1
