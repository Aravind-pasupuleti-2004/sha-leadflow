from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func

from app.extensions import db
from app.models import Activity, Lead


def test_create_lead_from_form_normalizes_contact_data(auth_client, form_data):
    response = auth_client.post("/leads/new", data=form_data())
    assert response.status_code == 302

    lead = db.session.scalars(db.select(Lead)).one()
    assert lead.name == "Aarav Fictional"
    assert lead.normalized_phone == "9000000001"
    assert lead.email == "aarav.fictional@example.com"
    assert lead.status == "New"
    assert 0 <= lead.score <= 100
    assert lead.score_factors["factors"]
    assert any(activity.kind == "created" for activity in lead.activities)


def test_create_lead_rejects_missing_contact(auth_client, form_data):
    response = auth_client.post(
        "/leads/new", data=form_data(phone="", email="")
    )
    assert response.status_code == 200
    assert b"at least one contact" in response.data
    assert db.session.scalar(db.select(func.count(Lead.id))) == 0


def test_duplicate_email_is_detected_before_insert(auth_client, form_data, make_lead):
    existing = make_lead(email="duplicate@example.com", phone="9000000999")
    payload = form_data(phone="9000000888", email="DUPLICATE@example.com")
    response = auth_client.post("/leads/new", data=payload)
    assert response.status_code == 200
    assert b"already exists" in response.data
    assert db.session.scalar(db.select(func.count(Lead.id))) == 1
    assert existing.email == "duplicate@example.com"


def test_duplicate_phone_is_normalized_before_check(auth_client, form_data, make_lead):
    make_lead(phone="9000000777", email="first@example.com")
    payload = form_data(phone="+91 90000 00777", email="second@example.com")
    response = auth_client.post("/leads/new", data=payload)
    assert response.status_code == 200
    assert b"already exists" in response.data
    assert db.session.scalar(db.select(func.count(Lead.id))) == 1


def test_edit_lead_updates_status_score_and_activity(auth_client, make_lead, form_data):
    lead = make_lead(status="New", budget_min=100000, budget_max=150000)
    old_score = lead.score
    payload = form_data(
        name=lead.name,
        phone=lead.phone,
        email=lead.email,
        status="Qualified",
        budget_min="1500000",
        budget_max="2500000",
    )
    response = auth_client.post(f"/leads/{lead.id}/edit", data=payload)
    assert response.status_code == 302
    db.session.refresh(lead)
    assert lead.status == "Qualified"
    assert lead.budget_min == 1500000 and lead.budget_max == 2500000
    assert lead.score >= old_score
    kinds = {activity.kind for activity in lead.activities}
    assert {"updated", "status_changed"}.issubset(kinds)


def test_edit_detects_duplicate_excluding_current_lead(auth_client, make_lead, form_data):
    first = make_lead(email="one@example.com", phone="9000000111")
    second = make_lead(email="two@example.com", phone="9000000222")
    payload = form_data(
        name=second.name,
        phone=second.phone,
        email="one@example.com",
    )
    response = auth_client.post(f"/leads/{second.id}/edit", data=payload)
    assert response.status_code == 200
    assert b"already exists" in response.data
    db.session.refresh(second)
    assert second.email == "two@example.com"


def test_status_endpoint_records_activity(auth_client, make_lead):
    lead = make_lead(status="New")
    response = auth_client.post(
        f"/leads/{lead.id}/status", data={"status": "Contacted"}
    )
    assert response.status_code == 302
    db.session.refresh(lead)
    assert lead.status == "Contacted"
    update = db.session.scalars(
        db.select(Activity).where(
            Activity.lead_id == lead.id, Activity.kind == "status_changed"
        )
    ).first()
    assert update is not None
    assert "New to Contacted" in update.message


def test_invalid_status_is_rejected(auth_client, make_lead):
    lead = make_lead(status="New")
    response = auth_client.post(
        f"/leads/{lead.id}/status", data={"status": "Imaginary"}
    )
    assert response.status_code == 302
    db.session.refresh(lead)
    assert lead.status == "New"


def test_search_status_filter_and_sort(auth_client, make_lead):
    alpha = make_lead(name="Zoya Fictional", locality="Whitefield", status="Contacted")
    make_lead(name="Beta Fictional", locality="Jayanagar", status="New")

    response = auth_client.get("/leads/?q=Zoya")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Zoya Fictional" in text
    assert "Beta Fictional" not in text

    response = auth_client.get("/leads/?status=Contacted")
    text = response.get_data(as_text=True)
    assert "Zoya Fictional" in text
    assert "Beta Fictional" not in text

    response = auth_client.get("/leads/?sort=name")
    assert response.status_code == 200
    assert alpha.name in response.get_data(as_text=True)


def test_pagination_returns_twenty_per_page(auth_client, make_lead):
    for _ in range(22):
        make_lead()
    response = auth_client.get("/leads/?page=2")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Showing 21" in text
    assert "of 22" in text


def test_lead_detail_renders_score_breakdown(auth_client, make_lead):
    lead = make_lead()
    response = auth_client.get(f"/leads/{lead.id}")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert lead.name in text
    assert "Budget fit" in text
    assert "Deterministic" in text


def test_form_validation_rejects_bad_budget_range(auth_client, form_data):
    response = auth_client.post(
        "/leads/new",
        data=form_data(budget_min="2000000", budget_max="1000000"),
    )
    assert response.status_code == 200
    assert b"Maximum budget" in response.data


def test_form_validation_reports_overlong_fields(auth_client, form_data):
    response = auth_client.post(
        "/leads/new",
        data=form_data(name="A" * 121, requirements="R" * 5001),
    )
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "120 characters or fewer" in text
    assert "5000 characters or fewer" in text
    assert db.session.scalar(db.select(func.count(Lead.id))) == 0
