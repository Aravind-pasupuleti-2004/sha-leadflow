"""Application factory for SHA LeadFlow AI."""

from __future__ import annotations

import logging
import os

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from flask_wtf.csrf import CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix

from .cli import register_cli
from .config import DEV_SECRET, get_config
from .extensions import csrf, db, migrate
from .routes import auth, dashboard, followups, health, leads, whatsapp_webhook
from .services.ai import ai_is_configured
from .services.scoring import band_label
from .utils import (
    budget_label,
    format_date,
    format_datetime,
    format_inr,
    initials,
    local_today,
    provider_label,
    relative_due,
    slugify_status,
)

PUBLIC_ENDPOINTS = {"auth.login", "health.healthz", "static"}
INSECURE_SECRET_VALUES = {
    DEV_SECRET,
    "replace-with-a-long-random-value",
    "change-me",
    "change-this-before-first-run",
}


def create_app(config=None, overrides: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)

    if config is None:
        app.config.from_object(get_config())
    elif isinstance(config, str):
        app.config.from_object(get_config(config))
    elif isinstance(config, dict):
        app.config.from_object(get_config())
        app.config.update(config)
    else:
        app.config.from_object(config)
    if overrides:
        app.config.update(overrides)

    os.makedirs(app.instance_path, exist_ok=True)

    if app.config.get("APP_ENV") == "production":
        secret_key = str(app.config.get("SECRET_KEY") or "")
        if len(secret_key) < 32 or secret_key in INSECURE_SECRET_VALUES:
            raise RuntimeError(
                "SECRET_KEY must be a strong random value of at least 32 characters in production."
            )
        database_uri = str(app.config.get("SQLALCHEMY_DATABASE_URI", ""))
        if not database_uri.startswith("postgresql"):
            raise RuntimeError(
                "DATABASE_URL must point to PostgreSQL in production. "
                "SQLite is a local-development-only fallback."
            )

    if app.config.get("TRUST_PROXY"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    csrf.init_app(app)

    # Importing models before migrations/CLI commands ensures metadata is ready.
    from . import models  # noqa: F401

    app.register_blueprint(auth.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(leads.bp, url_prefix="/leads")
    app.register_blueprint(followups.bp, url_prefix="/followups")
    app.register_blueprint(health.bp)
    app.register_blueprint(whatsapp_webhook.bp)
    register_cli(app)

    @app.before_request
    def load_logged_in_user():
        if request.endpoint in {"health.healthz", "static"}:
            g.user = None
            return None
        user_id = session.get("user_id")
        g.user = db.session.get(models.User, user_id) if user_id else None
        return None

    @app.before_request
    def require_login():
        if request.endpoint in PUBLIC_ENDPOINTS:
            return None
        if g.user is None:
            next_path = request.full_path if request.query_string else request.path
            if next_path.endswith("?"):
                next_path = next_path[:-1]
            return redirect(url_for("auth.login", next=next_path))
        return None

    @app.context_processor
    def inject_template_globals():
        return {
            "app_name": app.config["APP_NAME"],
            "lead_statuses": app.config["LEAD_STATUSES"],
            "lead_sources": app.config["LEAD_SOURCES"],
            "property_types": app.config["PROPERTY_TYPES"],
            "project_types": app.config["PROJECT_TYPES"],
            "high_priority_threshold": app.config["HIGH_PRIORITY_THRESHOLD"],
            "warm_priority_threshold": app.config["WARM_PRIORITY_THRESHOLD"],
            "ai_configured": ai_is_configured(app.config),
            "max_csv_mb": max(1, int(app.config["MAX_CSV_BYTES"]) // (1024 * 1024)),
            "max_csv_rows": int(app.config["MAX_CSV_ROWS"]),
            "current_year": local_today(app.config["TIMEZONE"]).year,
            "today": local_today(app.config["TIMEZONE"]),
        }

    app.jinja_env.filters["inr"] = format_inr
    app.jinja_env.filters["budget"] = lambda minimum, maximum=None: budget_label(minimum, maximum)
    app.jinja_env.filters["datefmt"] = format_date
    app.jinja_env.filters["datetimefmt"] = format_datetime
    app.jinja_env.filters["due_label"] = relative_due
    app.jinja_env.filters["statusclass"] = slugify_status
    app.jinja_env.filters["initials"] = initials
    app.jinja_env.filters["provider"] = provider_label
    app.jinja_env.globals["band_label"] = band_label
    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True

    @app.after_request
    def add_security_headers(response):
        if request.endpoint != "static":
            response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), camera=(), microphone=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'",
        )
        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    @app.errorhandler(400)
    def bad_request(error):
        return render_template("errors/400.html", message="The request could not be processed."), 400

    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def request_too_large(error):
        return (
            render_template(
                "errors/413.html",
                message="That upload is too large. The request limit is 6 MB.",
            ),
            413,
        )

    @app.errorhandler(429)
    def too_many_requests(error):
        response = render_template(
            "errors/429.html",
            message="Too many requests from this browser. Please wait a minute and try again.",
        )
        response = app.make_response(response)
        response.status_code = 429
        response.headers["Retry-After"] = "60"
        return response

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return render_template(
            "errors/400.html",
            message="Your form session expired or the security token was invalid. Reload and try again.",
        ), 400

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        app.logger.exception("Unhandled application error")
        return render_template("errors/500.html"), 500

    if not app.testing:
        level = getattr(logging, str(app.config.get("LOG_LEVEL", "INFO")).upper(), logging.INFO)
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )
        app.logger.setLevel(level)

    return app
