"""Lead CRUD, duplicate detection, activity history, and CSV import."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Activity, Lead, utcnow
from .scoring import score_lead, recalculate_score
from .automation import enqueue_automation
from .validation import (
    form_data_from_lead,
    normalize_email,
    normalize_phone,
    validate_lead_payload,
)

CSV_COLUMNS = [
    "name",
    "phone",
    "email",
    "locality",
    "property_type",
    "project_type",
    "budget_min",
    "budget_max",
    "expected_start",
    "requirements",
    "source",
    "status",
]
CSV_REQUIRED_COLUMNS = {"name", "phone", "email"}

CSV_TEMPLATE = (
    "name,phone,email,locality,property_type,project_type,budget_min,budget_max,"
    "expected_start,requirements,source,status\r\n"
    "Sample Customer,9000000001,sample.customer@example.com,Indiranagar,Apartment,"
    "Full Home Interiors,800000,1200000,2026-12-15,\"3BHK, move in by January, "
    "need full interiors\",Website,New\r\n"
)


class CsvImportError(ValueError):
    """A whole-file validation error (as opposed to one bad row)."""


@dataclass
class ImportIssue:
    row: int | None
    message: str
    kind: str = "error"


@dataclass
class ImportResult:
    total_rows: int = 0
    created: int = 0
    skipped: int = 0
    errors: list[ImportIssue] = field(default_factory=list)

    @property
    def failed(self) -> int:
        return sum(1 for issue in self.errors if issue.kind == "error")


def find_duplicate(phone: str | None, email: str | None, exclude_id: int | None = None) -> Lead | None:
    normalized_phone = normalize_phone(phone)
    normalized_email = normalize_email(email)
    conditions = []
    if normalized_phone:
        conditions.append(Lead.normalized_phone == normalized_phone)
    if normalized_email:
        conditions.append(Lead.normalized_email == normalized_email)
    if not conditions:
        return None
    statement = db.select(Lead).where(or_(*conditions))
    if exclude_id is not None:
        statement = statement.where(Lead.id != exclude_id)
    return db.session.scalars(statement).first()


def duplicate_message(lead: Lead) -> str:
    return f"A lead with this phone or email already exists: {lead.name} (#{lead.id})."


def log_activity(
    lead: Lead,
    kind: str,
    message: str,
    user_id: int | None = None,
    details: dict | None = None,
    commit: bool = False,
) -> Activity:
    activity = Activity(
        lead=lead,
        user_id=user_id,
        kind=kind,
        message=message,
        details=details or {},
    )
    db.session.add(activity)
    if commit:
        db.session.commit()
    return activity



def create_lead(data: dict, config, user_id: int | None = None) -> Lead:
    lead = Lead(**data)
    recalculate_score(lead, config)
    db.session.add(lead)
    db.session.flush()
    
    # Create default WhatsApp consent record (opted_out by default, admin can opt-in)
    # For testing/development, allow opting in via config
    auto_opt_in = config.get("AUTOMATION_AUTO_OPT_IN", False)
    from ..models import WhatsAppConsent
    consent = WhatsAppConsent(
        lead_id=lead.id,
        opted_in=auto_opt_in,
        consented_at=datetime.now(timezone.utc).replace(tzinfo=None) if auto_opt_in else None,
        consent_source="auto_opt_in" if auto_opt_in else None,
    )
    db.session.add(consent)
    
    log_activity(lead, "created", "Lead created", user_id=user_id)
    enqueue_automation(lead, config, user_id)
    return lead

def update_lead(lead: Lead, data: dict, config, user_id: int | None = None) -> list[str]:
    old_status = lead.status
    old_values = {
        "name": lead.name,
        "phone": lead.phone,
        "email": lead.email,
        "locality": lead.locality,
        "property_type": lead.property_type,
        "project_type": lead.project_type,
        "budget_min": lead.budget_min,
        "budget_max": lead.budget_max,
        "expected_start": lead.expected_start,
        "requirements": lead.requirements,
        "source": lead.source,
    }
    for key, value in data.items():
        setattr(lead, key, value)

    changed = [key for key, old in old_values.items() if getattr(lead, key) != old]
    recalculate_score(lead, config)
    if changed:
        log_activity(
            lead,
            "updated",
            f"Lead details updated ({', '.join(label.replace('_', ' ') for label in changed)}).",
            user_id=user_id,
            details={"fields": changed},
        )
    if lead.status != old_status:
        log_activity(
            lead,
            "status_changed",
            f"Status changed from {old_status} to {lead.status}.",
            user_id=user_id,
            details={"from": old_status, "to": lead.status},
        )
    return changed


def change_status(lead: Lead, new_status: str, config, user_id: int | None = None) -> bool:
    if new_status not in config["LEAD_STATUSES"]:
        raise ValueError("Invalid status.")
    if new_status == lead.status:
        return False
    old = lead.status
    lead.status = new_status
    log_activity(
        lead,
        "status_changed",
        f"Status changed from {old} to {new_status}.",
        user_id=user_id,
        details={"from": old, "to": new_status},
    )
    return True


def save_qualification(lead: Lead, result, user_id: int | None = None) -> None:
    lead.ai_summary = result.summary
    lead.ai_next_action = result.next_action
    lead.ai_extracted = result.as_dict()
    lead.ai_provider = result.provider
    lead.ai_updated_at = utcnow()
    note = f"AI insight generated via {result.provider_label}." if not result.fallback else (
        "AI unavailable; deterministic insight generated."
    )
    log_activity(
        lead,
        "ai_qualified",
        note,
        user_id=user_id,
        details={"provider": result.provider, "fallback_reason": result.fallback_reason},
    )


def _parse_csv_headers(fieldnames: list[str] | None) -> tuple[list[str], str | None]:
    if not fieldnames:
        return [], "The CSV file has no header row."
    normalized = []
    for field in fieldnames:
        key = (field or "").strip().lower()
        if not key:
            return [], "The CSV header contains an empty column name."
        normalized.append(key)
    if len(normalized) != len(set(normalized)):
        return [], "The CSV header contains duplicate column names."
    missing = CSV_REQUIRED_COLUMNS - set(normalized)
    if missing:
        return [], "Missing required column(s): " + ", ".join(sorted(missing)) + "."
    unknown = [name for name in normalized if name not in CSV_COLUMNS]
    if unknown:
        return [], "Unexpected column(s): " + ", ".join(unknown) + ". Download the template."
    return normalized, None


def import_leads_csv(stream, config, user_id: int | None = None) -> ImportResult:
    max_bytes = int(config["MAX_CSV_BYTES"])
    max_rows = int(config["MAX_CSV_ROWS"])
    raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise CsvImportError(f"CSV file is larger than the {max_bytes // 1024} KB limit.")
    if not raw:
        raise CsvImportError("The uploaded CSV file is empty.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvImportError("CSV must be UTF-8 encoded.") from exc

    reader = csv.DictReader(io.StringIO(text))
    headers, header_error = _parse_csv_headers(reader.fieldnames)
    if header_error:
        raise CsvImportError(header_error)

    rows = list(reader)
    if len(rows) > max_rows:
        raise CsvImportError(f"CSV has more than {max_rows} data rows.")

    result = ImportResult(total_rows=len(rows))
    for index, raw_row in enumerate(rows, start=2):
        if None in raw_row:
            result.errors.append(ImportIssue(index, "Row has more values than the header."))
            continue
        row = {
            (key or "").strip().lower(): (value or "").strip()
            for key, value in raw_row.items()
            if key is not None
        }
        if not any(row.values()):
            result.total_rows -= 1
            continue

        data, errors = validate_lead_payload(row, config)
        if errors:
            message = "; ".join(errors[key] for key in sorted(errors))
            result.errors.append(ImportIssue(index, message))
            continue

        duplicate = find_duplicate(data["normalized_phone"], data["normalized_email"])
        if duplicate:
            result.skipped += 1
            result.errors.append(
                ImportIssue(index, f"Skipped duplicate of {duplicate.name} (#{duplicate.id}).", "skipped")
            )
            continue

        try:
            with db.session.begin_nested():
                lead = Lead(**data)
                recalculate_score(lead, config)
                db.session.add(lead)
                db.session.flush()
                db.session.add(
                    Activity(
                        lead=lead,
                        user_id=user_id,
                        kind="imported",
                        message="Imported from CSV.",
                        details={"row": index},
                    )
                )
            result.created += 1
        except IntegrityError:
            result.skipped += 1
            result.errors.append(
                ImportIssue(index, "Skipped because a unique phone or email already exists.", "skipped")
            )
    db.session.commit()
    return result


__all__ = [
    "CSV_COLUMNS",
    "CSV_TEMPLATE",
    "CsvImportError",
    "ImportIssue",
    "ImportResult",
    "change_status",
    "create_lead",
    "duplicate_message",
    "find_duplicate",
    "form_data_from_lead",
    "import_leads_csv",
    "log_activity",
    "recalculate_score",
    "save_qualification",
    "update_lead",
]
