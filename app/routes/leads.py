"""Lead list, create, edit, detail, status, CSV, and AI routes."""

from __future__ import annotations

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Lead
from ..ratelimit import rate_limit
from ..services.ai import build_provider, qualify_lead
from ..services.leads import (
    CSV_COLUMNS,
    CSV_TEMPLATE,
    CsvImportError,
    change_status,
    create_lead,
    duplicate_message,
    find_duplicate,
    form_data_from_lead,
    import_leads_csv,
    save_qualification,
    update_lead,
)
from ..services.scoring import recalculate_score
from ..services.validation import validate_lead_payload

bp = Blueprint("leads", __name__)

SORT_OPTIONS = {
    "recent": ("Recently updated", Lead.updated_at.desc()),
    "newest": ("Newest first", Lead.created_at.desc()),
    "score": ("Highest score", Lead.score.desc()),
    "name": ("Name A–Z", Lead.name.asc()),
    "start": ("Start date", Lead.expected_start.asc()),
}


def _form_defaults() -> dict:
    return {"source": "Website", "status": "New"}


@bp.get("/")
def index():
    q = (request.args.get("q") or "").strip()[:120]
    status = (request.args.get("status") or "").strip()
    source = (request.args.get("source") or "").strip()
    sort = request.args.get("sort", "recent")
    if sort not in SORT_OPTIONS:
        sort = "recent"
    page = max(1, request.args.get("page", 1, type=int) or 1)

    query = Lead.query
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            or_(
                Lead.name.ilike(pattern),
                Lead.phone.ilike(pattern),
                Lead.email.ilike(pattern),
                Lead.locality.ilike(pattern),
                Lead.requirements.ilike(pattern),
            )
        )
    if status in current_app.config["LEAD_STATUSES"]:
        query = query.filter(Lead.status == status)
    else:
        status = ""
    if source in current_app.config["LEAD_SOURCES"]:
        query = query.filter(Lead.source == source)
    else:
        source = ""

    order = SORT_OPTIONS[sort][1]
    pagination = query.order_by(order, Lead.id.desc()).paginate(
        page=page, per_page=current_app.config["DESIRED_PAGE_SIZE"], error_out=False
    )
    return render_template(
        "leads/list.html",
        pagination=pagination,
        leads=pagination.items,
        q=q,
        status=status,
        source=source,
        sort=sort,
        sort_options=SORT_OPTIONS,
    )


@bp.get("/new")
def new():
    return render_template(
        "leads/form.html",
        mode="create",
        form_data=_form_defaults(),
        errors={},
        lead=None,
    )


@bp.post("/new")
@rate_limit("lead_submit", "LEAD_RATE_LIMIT_PER_MINUTE")
def create():
    form_data = request.form.to_dict()
    data, errors = validate_lead_payload(request.form, current_app.config)
    if not errors:
        duplicate = find_duplicate(data["normalized_phone"], data["normalized_email"])
        if duplicate:
            errors["duplicate"] = duplicate_message(duplicate)
    if errors:
        flash("Please correct the highlighted fields.", "error")
        return render_template(
            "leads/form.html", mode="create", form_data=form_data, errors=errors, lead=None
        )

    try:
        lead = create_lead(data, current_app.config, user_id=g.user.id)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        errors["duplicate"] = "A lead with this phone or email already exists."
        flash("That lead already exists.", "error")
        return render_template(
            "leads/form.html", mode="create", form_data=form_data, errors=errors, lead=None
        )

    flash(f"Lead created and scored {lead.score}/100.", "success")
    return redirect(url_for("leads.detail", lead_id=lead.id))


@bp.get("/<int:lead_id>")
def detail(lead_id: int):
    lead = db.get_or_404(Lead, lead_id)
    return render_template(
        "leads/detail.html",
        lead=lead,
        score=lead.score_factors or {},
    )


@bp.route("/<int:lead_id>/edit", methods=["GET", "POST"])
def edit(lead_id: int):
    lead = db.get_or_404(Lead, lead_id)
    if request.method == "GET":
        return render_template(
            "leads/form.html",
            mode="edit",
            form_data=form_data_from_lead(lead),
            errors={},
            lead=lead,
        )

    form_data = request.form.to_dict()
    data, errors = validate_lead_payload(request.form, current_app.config)
    if not errors:
        duplicate = find_duplicate(
            data["normalized_phone"], data["normalized_email"], exclude_id=lead.id
        )
        if duplicate:
            errors["duplicate"] = duplicate_message(duplicate)
    if errors:
        flash("Please correct the highlighted fields.", "error")
        return render_template(
            "leads/form.html", mode="edit", form_data=form_data, errors=errors, lead=lead
        )

    try:
        changed = update_lead(lead, data, current_app.config, user_id=g.user.id)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        errors["duplicate"] = "A lead with this phone or email already exists."
        flash("That contact is already used by another lead.", "error")
        return render_template(
            "leads/form.html", mode="edit", form_data=form_data, errors=errors, lead=lead
        )

    if changed:
        flash("Lead updated and rescored.", "success")
    else:
        flash("No changes were needed.", "info")
    return redirect(url_for("leads.detail", lead_id=lead.id))


@bp.post("/<int:lead_id>/status")
def update_status(lead_id: int):
    lead = db.get_or_404(Lead, lead_id)
    new_status = (request.form.get("status") or "").strip()
    try:
        changed = change_status(
            lead, new_status, current_app.config, user_id=g.user.id
        )
    except ValueError:
        flash("That status is not valid.", "error")
        return redirect(url_for("leads.detail", lead_id=lead.id))
    if changed:
        db.session.commit()
        flash(f"Status changed to {new_status}.", "success")
    else:
        flash("Status is unchanged.", "info")
    return redirect(url_for("leads.detail", lead_id=lead.id))


@bp.get("/import")
def import_page():
    return render_template(
        "leads/import.html",
        columns=CSV_COLUMNS,
        result=None,
    )


@bp.get("/import/template")
def import_template():
    return Response(
        CSV_TEMPLATE,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=sha-leadflow-template.csv"},
    )


@bp.post("/import")
@rate_limit("lead_import", "LEAD_RATE_LIMIT_PER_MINUTE")
def import_csv():
    uploaded = request.files.get("csv_file")
    if uploaded is None or not uploaded.filename:
        flash("Choose a CSV file to import.", "error")
        return render_template("leads/import.html", columns=CSV_COLUMNS, result=None), 400
    if not uploaded.filename.lower().endswith(".csv"):
        flash("Only .csv files are accepted.", "error")
        return render_template("leads/import.html", columns=CSV_COLUMNS, result=None), 400
    try:
        result = import_leads_csv(uploaded.stream, current_app.config, user_id=g.user.id)
    except CsvImportError as exc:
        flash(str(exc), "error")
        return render_template("leads/import.html", columns=CSV_COLUMNS, result=None), 400

    if result.created:
        flash(
            f"Import finished: {result.created} created, {result.skipped} skipped, "
            f"{result.failed} row errors.",
            "success" if not result.failed else "warning",
        )
    else:
        flash("No leads were imported. Review the issues below.", "error")
    return render_template("leads/import.html", columns=CSV_COLUMNS, result=result)


@bp.post("/<int:lead_id>/qualify")
@rate_limit("ai_qualify", "AI_RATE_LIMIT_PER_MINUTE")
def qualify(lead_id: int):
    lead = db.get_or_404(Lead, lead_id)
    score_result = recalculate_score(lead, current_app.config)
    provider = build_provider(current_app.config, logger=current_app.logger)
    result = qualify_lead(
        lead,
        score_result,
        current_app.config,
        logger=current_app.logger,
        provider=provider,
    )
    save_qualification(lead, result, user_id=g.user.id)
    db.session.commit()
    if result.fallback:
        flash(
            "The AI provider was unavailable, so a rule-based insight was saved. "
            "Score and CRM data are unaffected.",
            "warning",
        )
    else:
        flash(f"AI insight generated with {result.provider_label}.", "success")
    return redirect(url_for("leads.detail", lead_id=lead.id))
