from __future__ import annotations

import pytest

from app import create_app
from app import config as config_module
from app.models import Lead
from app.extensions import db
from sqlalchemy import func


def test_csrf_protection_rejects_missing_token(auth_client, app, form_data):
    app.config["WTF_CSRF_ENABLED"] = True
    response = auth_client.post("/leads/new", data=form_data())
    assert response.status_code == 400
    assert b"security token" in response.data
    assert db.session.scalar(db.select(func.count(Lead.id))) == 0


def test_csrf_protection_accepts_valid_token(auth_client, app, form_data):
    app.config["WTF_CSRF_ENABLED"] = True
    page = auth_client.get("/leads/new")
    assert page.status_code == 200
    token = page.get_data(as_text=True).split('name="csrf_token" value="')[1].split('"')[0]
    response = auth_client.post("/leads/new", data={**form_data(), "csrf_token": token})
    assert response.status_code == 302
    assert db.session.scalar(db.select(func.count(Lead.id))) == 1


def test_lead_submission_rate_limit(auth_client, app, form_data):
    app.config["RATELIMIT_ENABLED"] = True
    app.config["LEAD_RATE_LIMIT_PER_MINUTE"] = 1
    environ = {"REMOTE_ADDR": "10.77.77.77"}
    first = auth_client.post(
        "/leads/new",
        data=form_data(phone="9000055501", email="rate.one@example.com"),
        environ_base=environ,
    )
    assert first.status_code == 302
    second = auth_client.post(
        "/leads/new",
        data=form_data(phone="9000055502", email="rate.two@example.com"),
        environ_base=environ,
    )
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "60"
    assert db.session.scalar(db.select(func.count(Lead.id))) == 1


def test_production_refuses_default_secret(monkeypatch):
    monkeypatch.setattr(config_module.ProductionConfig, "SECRET_KEY", config_module.DEV_SECRET)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(config_module.ProductionConfig)


def test_production_refuses_sqlite_database():
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app(
            config_module.ProductionConfig,
            overrides={
                "SECRET_KEY": "a-strong-production-secret-for-this-test",
                "SQLALCHEMY_DATABASE_URI": "sqlite:///unsafe-production.db",
            },
        )


def test_production_refuses_placeholder_secret():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(
            config_module.ProductionConfig,
            overrides={"SECRET_KEY": "replace-with-a-long-random-value"},
        )
