"""Session authentication for the private CRM."""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from ..extensions import db
from ..models import User
from ..ratelimit import rate_limit
from ..services.validation import normalize_email

bp = Blueprint("auth", __name__)


def safe_next_url(target: str | None) -> str | None:
    """Only allow same-site relative redirects.

    The decoded target is inspected so that URL-encoded path separators
    (``%2F``), backslashes (``%5C``), protocol-relative URLs (``//``), and
    absolute URLs cannot be used to redirect to an external host.
    """
    if not target:
        return None
    if any(character in target for character in ("\\", "\r", "\n", "\x00")):
        return None
    decoded = unquote(target)
    if any(character in decoded for character in ("\\", "\r", "\n", "\x00")):
        return None
    parts = urlsplit(decoded)
    if parts.scheme or parts.netloc:
        return None
    if not decoded.startswith("/") or decoded.startswith("//"):
        return None
    return target


@bp.route("/login", methods=["GET", "POST"])
@rate_limit("login", "LOGIN_RATE_LIMIT_PER_MINUTE")
def login():
    if g.user is not None:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email = normalize_email(request.form.get("email"))
        password = request.form.get("password") or ""
        user = None
        if email:
            user = db.session.scalars(
                db.select(User).where(User.normalized_email == email)
            ).first()
        if user is None or not user.is_active or not user.check_password(password):
            flash("Invalid email or password.", "error")
            return render_template("auth/login.html", email=email or ""), 200

        session.clear()
        session["user_id"] = user.id
        session.permanent = True
        target = safe_next_url(request.args.get("next") or request.form.get("next"))
        flash(f"Welcome back, {user.name.split()[0]}.", "success")
        return redirect(target or url_for("dashboard.index"))

    return render_template("auth/login.html", email="")


@bp.post("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
