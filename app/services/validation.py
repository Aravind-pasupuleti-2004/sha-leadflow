"""Server-side validation and normalization for every lead input path."""

from __future__ import annotations

import re
from datetime import date, datetime

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
PHONE_CHARS_RE = re.compile(r"^[0-9+\-().\s]+$")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

MAX_BUDGET = 1_000_000_000
NAME_MAX = 120
EMAIL_MAX = 254
PHONE_MAX = 32
LOCALITY_MAX = 120
REQUIREMENTS_MAX = 5000


def normalize_phone(raw: str | None) -> str | None:
    if raw is None:
        return None
    raw = str(raw).strip()
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if len(digits) == 14 and digits.startswith("0091"):
        digits = digits[4:]
    elif len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits or None


def normalize_email(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip().lower()
    return value or None


def clean_text(raw: str | None, max_length: int) -> str:
    value = CONTROL_RE.sub(" ", str(raw or "")).strip()
    return value[:max_length]


def clean_text_checked(
    raw: str | None,
    max_length: int,
    field: str,
    label: str,
    errors: dict[str, str],
) -> str:
    """Clean text and report (rather than silently hide) overlong input."""
    value = CONTROL_RE.sub(" ", str(raw or "")).strip()
    if len(value) > max_length:
        errors[field] = f"{label} must be {max_length} characters or fewer."
    return value[:max_length]


def parse_budget(raw: str | None) -> int | None:
    if raw is None:
        return None
    value = str(raw).strip().replace(",", "").replace("₹", "").replace(" ", "")
    if not value:
        return None
    if not value.isdigit():
        raise ValueError("Budget must be a whole number in rupees.")
    number = int(value)
    if number < 0 or number > MAX_BUDGET:
        raise ValueError("Budget must be between ₹0 and ₹100 crore.")
    return number


def parse_expected_start(raw: str | None) -> date | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError("Expected start must be a valid date (YYYY-MM-DD).")


def validate_lead_payload(raw, config) -> tuple[dict, dict]:
    """Validate a form or CSV row.

    Returns ``(cleaned, errors)``. ``cleaned`` contains normalized values and is
    only safe to save when ``errors`` is empty.
    """
    errors: dict[str, str] = {}
    data: dict = {}

    raw_name = clean_text_checked(raw.get("name"), NAME_MAX, "name", "Lead name", errors)
    name = " ".join(raw_name.split())
    if len(name) < 2 and "name" not in errors:
        errors["name"] = "Enter the lead's name (at least 2 characters)."
    data["name"] = name

    raw_phone = clean_text_checked(raw.get("phone"), PHONE_MAX, "phone", "Phone number", errors)
    if raw_phone and not PHONE_CHARS_RE.match(raw_phone):
        errors["phone"] = "Phone can contain digits, spaces, +, -, dots, and brackets only."
    normalized_phone = normalize_phone(raw_phone)
    if raw_phone and (not normalized_phone or not 10 <= len(normalized_phone) <= 15):
        errors["phone"] = "Enter a valid phone number (10–15 digits, with optional country code)."
    data["phone"] = raw_phone or None
    data["normalized_phone"] = normalized_phone

    raw_email = clean_text_checked(raw.get("email"), EMAIL_MAX, "email", "Email", errors)
    normalized_email = normalize_email(raw_email)
    if raw_email and normalized_email and not EMAIL_RE.match(normalized_email):
        errors["email"] = "Enter a valid email address."
    if not raw_phone and not raw_email:
        errors["contact"] = "Provide at least one contact method: phone or email."
    data["email"] = normalized_email
    data["normalized_email"] = normalized_email

    data["locality"] = (
        clean_text_checked(raw.get("locality"), LOCALITY_MAX, "locality", "Locality", errors) or None
    )

    property_type = clean_text(raw.get("property_type"), 40)
    if property_type and property_type not in config["PROPERTY_TYPES"]:
        errors["property_type"] = "Choose a valid property type."
    data["property_type"] = property_type or None

    project_type = clean_text(raw.get("project_type"), 40)
    if project_type and project_type not in config["PROJECT_TYPES"]:
        errors["project_type"] = "Choose a valid project type."
    data["project_type"] = project_type or None

    try:
        budget_min = parse_budget(raw.get("budget_min"))
        data["budget_min"] = budget_min
    except ValueError as exc:
        errors["budget_min"] = str(exc)
    try:
        budget_max = parse_budget(raw.get("budget_max"))
        data["budget_max"] = budget_max
    except ValueError as exc:
        errors["budget_max"] = str(exc)
    if (
        "budget_min" not in errors
        and "budget_max" not in errors
        and data.get("budget_min") is not None
        and data.get("budget_max") is not None
        and data["budget_max"] < data["budget_min"]
    ):
        errors["budget_max"] = "Maximum budget must be greater than or equal to the minimum."

    try:
        data["expected_start"] = parse_expected_start(raw.get("expected_start"))
    except ValueError as exc:
        errors["expected_start"] = str(exc)

    requirements = clean_text_checked(
        raw.get("requirements"), REQUIREMENTS_MAX, "requirements", "Requirements", errors
    )
    data["requirements"] = requirements or None

    source = clean_text(raw.get("source"), 40) or "Other"
    if source not in config["LEAD_SOURCES"]:
        errors["source"] = "Choose a valid lead source."
    data["source"] = source

    status = clean_text(raw.get("status"), 30) or "New"
    if status not in config["LEAD_STATUSES"]:
        errors["status"] = "Choose a valid lead status."
    data["status"] = status

    return data, errors


def form_data_from_lead(lead) -> dict:
    return {
        "name": lead.name,
        "phone": lead.phone or "",
        "email": lead.email or "",
        "locality": lead.locality or "",
        "property_type": lead.property_type or "",
        "project_type": lead.project_type or "",
        "budget_min": "" if lead.budget_min is None else str(lead.budget_min),
        "budget_max": "" if lead.budget_max is None else str(lead.budget_max),
        "expected_start": lead.expected_start.isoformat() if lead.expected_start else "",
        "requirements": lead.requirements or "",
        "source": lead.source or "Other",
        "status": lead.status or "New",
    }
