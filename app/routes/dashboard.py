"""Dashboard route."""

from __future__ import annotations

from flask import Blueprint, current_app, render_template

from ..services.dashboard import build_dashboard

bp = Blueprint("dashboard", __name__)


@bp.get("/")
def index():
    data = build_dashboard(current_app.config)
    return render_template("dashboard.html", **data)
