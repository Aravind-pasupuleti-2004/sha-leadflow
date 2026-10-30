"""Health-check endpoint for Render and other hosting platforms."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from ..extensions import db
from ..services.ai import ai_is_configured

bp = Blueprint("health", __name__)


@bp.get("/healthz")
def healthz():
    database_ok = True
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception:  # never expose exception details publicly
        db.session.rollback()
        database_ok = False
    payload = {
        "status": "ok" if database_ok else "degraded",
        "database": "ok" if database_ok else "error",
        "ai_configured": ai_is_configured(current_app.config),
    }
    response = jsonify(payload)
    response.status_code = 200 if database_ok else 503
    response.headers["Cache-Control"] = "no-store"
    return response
