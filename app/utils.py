"""Small presentation and date helpers shared by services and templates."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


def local_today(timezone_name: str = "Asia/Kolkata") -> date:
    return datetime.now(ZoneInfo(timezone_name)).date()


def to_local_datetime(value: datetime | None, timezone_name: str = "Asia/Kolkata") -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo(timezone_name))


def format_inr(value: int | None) -> str:
    if value is None:
        return "—"
    number = int(value)
    digits = str(abs(number))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return f"{'-' if number < 0 else ''}{digits}"


def budget_label(budget_min: int | None, budget_max: int | None) -> str:
    if budget_min is None and budget_max is None:
        return "Not shared"
    if budget_min is not None and budget_max is not None:
        if budget_min == budget_max:
            return f"₹{format_inr(budget_min)}"
        return f"₹{format_inr(budget_min)} – ₹{format_inr(budget_max)}"
    if budget_min is not None:
        return f"From ₹{format_inr(budget_min)}"
    return f"Up to ₹{format_inr(budget_max)}"


def format_date(value: date | datetime | None, fmt: str = "%d %b %Y") -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        value = to_local_datetime(value).date()
    return value.strftime(fmt)


def format_datetime(value: datetime | None) -> str:
    local = to_local_datetime(value)
    if local is None:
        return "—"
    return local.strftime("%d %b %Y, %I:%M %p")


def relative_due(value: date | None, today: date | None = None) -> str:
    if value is None:
        return "No date"
    today = today or local_today()
    delta = (value - today).days
    if delta < 0:
        count = abs(delta)
        return f"Overdue by {count} day{'s' if count != 1 else ''}"
    if delta == 0:
        return "Due today"
    if delta == 1:
        return "Due tomorrow"
    if delta <= 7:
        return f"Due in {delta} days"
    return f"Due {format_date(value)}"


def slugify_status(status: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (status or "").lower()).strip("-") or "unknown"


def initials(name: str | None) -> str:
    parts = [part for part in (name or "").strip().split() if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def provider_label(provider: str | None) -> str:
    labels = {
        "gemini": "Gemini",
        "groq": "Groq",
        "fallback": "Rule-based fallback",
        "fake": "Test provider",
    }
    return labels.get((provider or "").lower(), "Not generated")
