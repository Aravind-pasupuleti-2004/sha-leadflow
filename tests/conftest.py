from __future__ import annotations

import itertools
from datetime import timedelta

import pytest

from app import create_app
from app.config import TestingConfig
from app.extensions import db
from app.models import FollowUp, Lead, User
from app.services.leads import create_lead
from app.services.validation import normalize_email, normalize_phone
from app.utils import local_today


@pytest.fixture()
def app(tmp_path):
    database = tmp_path / "test.db"
    application = create_app(
        TestingConfig,
        overrides={
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
            "SERVER_NAME": None,
        },
    )
    with application.app_context():
        db.create_all()
        user = User(
            name="Test Administrator",
            email="admin@example.com",
            normalized_email="admin@example.com",
        )
        user.set_password("test-password-123")
        db.session.add(user)
        db.session.commit()
        application.config["TEST_USER_ID"] = user.id
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth_client(app, client):
    with client.session_transaction() as session:
        session["user_id"] = app.config["TEST_USER_ID"]
    return client


@pytest.fixture()
def admin(app):
    return db.session.get(User, app.config["TEST_USER_ID"])


@pytest.fixture()
def make_lead(app):
    counter = itertools.count(1)

    def factory(**overrides):
        number = next(counter)
        payload = {
            "name": f"Test Lead {number}",
            "phone": f"900000{number:04d}",
            "email": f"test.lead.{number}@example.com",
            "locality": "Indiranagar",
            "property_type": "Apartment",
            "project_type": "Full Home Interiors",
            "budget_min": 600000,
            "budget_max": 900000,
            "expected_start": local_today() + timedelta(days=40),
            "requirements": (
                "3BHK full interiors with kitchen, wardrobes and false ceiling. "
                "Ready to finalise; site visit requested."
            ),
            "source": "Website",
            "status": "New",
        }
        payload.update(overrides)
        payload["normalized_phone"] = normalize_phone(payload.get("phone"))
        payload["normalized_email"] = normalize_email(payload.get("email"))
        lead = create_lead(payload, app.config)
        db.session.commit()
        return lead

    return factory


@pytest.fixture()
def form_data():
    def factory(**overrides):
        payload = {
            "name": "Aarav Fictional",
            "phone": "+91 90000 00001",
            "email": "aarav.fictional@example.com",
            "locality": "Indiranagar",
            "property_type": "Apartment",
            "project_type": "Full Home Interiors",
            "budget_min": "800000",
            "budget_max": "1200000",
            "expected_start": (local_today() + timedelta(days=20)).isoformat(),
            "requirements": "3BHK full interiors; ready to finalise and book a site visit.",
            "source": "Website",
            "status": "New",
        }
        payload.update(overrides)
        return payload

    return factory


@pytest.fixture()
def make_followup(app):
    def factory(lead, **overrides):
        values = {
            "title": "Call the customer",
            "due_date": local_today() - timedelta(days=1),
            "notes": "Fictional test note.",
        }
        values.update(overrides)
        followup = FollowUp(lead=lead, **values)
        db.session.add(followup)
        db.session.commit()
        return followup

    return factory


@pytest.fixture()
def lead_count(app):
    def count():
        return db.session.scalar(db.select(db.func.count(Lead.id)))

    return count
