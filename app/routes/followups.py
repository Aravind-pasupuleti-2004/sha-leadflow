"""Follow-up list and task routes."""

from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import FollowUp, Lead
from ..ratelimit import rate_limit
from ..services.ai import build_provider, generate_followup_draft
from ..services.followups import (
    complete_followup,
    create_followup,
    reopen_followup,
    save_draft,
    validate_followup_input,
)
from ..utils import local_today

bp = Blueprint("followups", __name__)


def _return_url(followup: FollowUp) -> str:
    target = request.form.get("return_to", "lead")
    if target == "dashboard":
        return url_for("dashboard.index")
    if target == "followups":
        return url_for("followups.index")
    return url_for("leads.detail", lead_id=followup.lead_id) + "#followups"


@bp.get("/")
def index():
    today = local_today(current_app.config["TIMEZONE"])
    view = request.args.get("view", "pending")
    if view not in {"pending", "overdue", "completed", "all"}:
        view = "pending"
    page = max(1, request.args.get("page", 1, type=int) or 1)

    statement = db.select(FollowUp).options(joinedload(FollowUp.lead))
    if view == "pending":
        statement = statement.where(FollowUp.status == "pending").order_by(
            FollowUp.due_date.asc(), FollowUp.id.asc()
        )
    elif view == "overdue":
        statement = statement.where(
            FollowUp.status == "pending", FollowUp.due_date < today
        ).order_by(FollowUp.due_date.asc())
    elif view == "completed":
        statement = statement.where(FollowUp.status == "completed").order_by(
            FollowUp.completed_at.desc().nullslast(), FollowUp.id.desc()
        )
    else:
        statement = statement.order_by(FollowUp.status.asc(), FollowUp.due_date.asc())

    pagination = db.paginate(
        statement, page=page, per_page=25, error_out=False
    )
    status_rows = db.session.execute(
        db.select(FollowUp.status, func.count(FollowUp.id)).group_by(FollowUp.status)
    ).all()
    counts = {status: 0 for status, _ in status_rows}
    counts.update({status: count for status, count in status_rows})
    overdue_count = db.session.execute(
        db.select(func.count(FollowUp.id)).where(
            FollowUp.status == "pending", FollowUp.due_date < today
        )
    ).scalar_one()

    return render_template(
        "followups/index.html",
        pagination=pagination,
        followups=pagination.items,
        view=view,
        counts=counts,
        overdue_count=overdue_count,
        today=today,
    )


@bp.post("/lead/<int:lead_id>")
def create(lead_id: int):
    lead = db.get_or_404(Lead, lead_id)
    data, errors = validate_followup_input(request.form)
    if errors:
        flash(next(iter(errors.values())), "error")
        return redirect(url_for("leads.detail", lead_id=lead.id) + "#followups")
    create_followup(lead, data, user_id=g.user.id)
    flash(f"Follow-up scheduled for {data['due_date'].strftime('%d %b %Y')}.", "success")
    return redirect(url_for("leads.detail", lead_id=lead.id) + "#followups")


@bp.post("/<int:followup_id>/complete")
def complete(followup_id: int):
    followup = db.get_or_404(FollowUp, followup_id)
    complete_followup(followup, user_id=g.user.id)
    flash("Follow-up marked complete.", "success")
    return redirect(_return_url(followup))


@bp.post("/<int:followup_id>/reopen")
def reopen(followup_id: int):
    followup = db.get_or_404(FollowUp, followup_id)
    reopen_followup(followup, user_id=g.user.id)
    flash("Follow-up reopened.", "info")
    return redirect(_return_url(followup))


@bp.post("/<int:followup_id>/draft")
@rate_limit("ai_draft", "AI_RATE_LIMIT_PER_MINUTE")
def draft(followup_id: int):
    followup = db.get_or_404(FollowUp, followup_id)
    provider = build_provider(current_app.config, logger=current_app.logger)
    result = generate_followup_draft(
        followup.lead,
        followup,
        current_app.config,
        logger=current_app.logger,
        provider=provider,
    )
    save_draft(followup, result, user_id=g.user.id)
    if result.fallback:
        flash(
            "AI was unavailable, so a rule-based draft was saved. Review it before copying.",
            "warning",
        )
    else:
        flash(f"Message draft generated with {result.provider_label}.", "success")
    return redirect(
        url_for("leads.detail", lead_id=followup.lead_id) + f"#followup-{followup.id}"
    )
