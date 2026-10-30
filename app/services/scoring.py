"""Deterministic, explainable lead scoring.

The AI provider is deliberately not involved in this calculation. Scores are
derived from business rules in configuration so they can be audited, tested,
and changed without retraining anything.
"""

from __future__ import annotations

from datetime import date, datetime

from ..utils import local_today

FACTOR_LABELS = {
    "budget": "Budget fit",
    "readiness": "Readiness & intent",
    "urgency": "Urgency",
    "scope": "Project scope fit",
    "area": "Service-area fit",
}

FACTOR_ORDER = ["budget", "readiness", "urgency", "scope", "area"]


def _as_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def _budget_factor(data: dict, cfg: dict, weight: int) -> tuple[int, str]:
    budget = data.get("budget_max") or data.get("budget_min")
    if not budget:
        return 0, "No budget range shared."
    for band in sorted(cfg["budget_bands"], key=lambda item: item["min"], reverse=True):
        if budget >= band["min"]:
            points = min(weight, int(band["points"]))
            return points, f"Budget aligned to the {band['label']} band."
    return 0, "Budget is below the smallest configured band."


def _readiness_factor(data: dict, cfg: dict, weight: int) -> tuple[int, str]:
    rules = cfg["readiness"]
    requirements = (data.get("requirements") or "").lower()
    points = 0
    reasons: list[str] = []

    if len(requirements) >= int(rules["detailed_length"]):
        points += int(rules["detailed_requirements"])
        reasons.append("detailed brief")
    elif len(requirements) >= int(rules["some_length"]):
        points += int(rules["some_requirements"])
        reasons.append("some brief detail")
    else:
        reasons.append("brief is thin")

    matched_keyword = next((kw for kw in rules["keywords"] if kw.lower() in requirements), None)
    if matched_keyword:
        points += int(rules["intent_keyword"])
        reasons.append(f"intent signal “{matched_keyword}”")
    if data.get("expected_start"):
        points += int(rules["timeline_shared"])
        reasons.append("timeline shared")
    if data.get("budget_min") or data.get("budget_max"):
        points += int(rules["budget_shared"])
        reasons.append("budget shared")

    points = min(weight, points)
    return points, "; ".join(reasons).capitalize() + "."


def _urgency_factor(data: dict, cfg: dict, weight: int, today: date) -> tuple[int, str]:
    rules = cfg["urgency"]
    requirements = (data.get("requirements") or "").lower()
    keyword = next((kw for kw in rules["keywords"] if kw.lower() in requirements), None)
    start = _as_date(data.get("expected_start"))

    timeline_points = None
    reason = "No start date shared."
    if start is not None:
        days = (start - today).days
        if days <= 0:
            timeline_points = int(rules["bands"][0]["points"])
            reason = "Start date is now or already past."
        else:
            for band in rules["bands"]:
                if days <= int(band["days"]):
                    timeline_points = int(band["points"])
                    reason = f"Start date is {days} day{'s' if days != 1 else ''} away."
                    break
            if timeline_points is None:
                timeline_points = int(rules["far_future"])
                reason = f"Start date is more than {rules['bands'][-1]['days']} days away."

    keyword_points = int(rules["keyword"]) if keyword else None
    if timeline_points is None and keyword_points is None:
        points = int(rules["unknown"])
        reason = "No timeline or urgency signal."
    else:
        points = max(value for value in (timeline_points, keyword_points) if value is not None)
        if keyword_points is not None and (timeline_points is None or keyword_points > timeline_points):
            reason = f"Urgency language found: “{keyword}”."

    return min(weight, points), reason


def _scope_factor(data: dict, cfg: dict, weight: int) -> tuple[int, str]:
    project = data.get("project_type") or ""
    rules = cfg["scope"]
    points = min(weight, int(rules["projects"].get(project, rules["default"])))
    if project and project in rules["projects"]:
        return points, f"{project} matches a configured scope tier."
    if project:
        return points, f"{project} is outside the main scope tiers."
    return points, "No project type shared."


def _area_factor(data: dict, cfg: dict, weight: int) -> tuple[int, str]:
    locality = (data.get("locality") or "").strip().lower()
    areas = [str(area).strip().lower() for area in cfg.get("service_areas", []) if str(area).strip()]
    if not locality:
        return 0, "No locality shared."
    if any(area == locality or area in locality for area in areas):
        return min(weight, int(cfg["area"]["points"])), f"{data.get('locality')} is in the service area."
    return 0, f"{data.get('locality')} is outside the configured service areas."


def score_lead(lead_data: dict, config, today: date | None = None) -> dict:
    """Return ``{total, band, factors, summary, scored_on}`` for a lead dict."""
    cfg = config.get("SCORING", config) if isinstance(config, dict) else config
    if not cfg:
        raise ValueError("Scoring configuration is missing.")
    today = today or local_today(config.get("TIMEZONE", "Asia/Kolkata") if isinstance(config, dict) else "Asia/Kolkata")
    weights = cfg["weights"]

    raw_factors = {
        "budget": _budget_factor(lead_data, cfg, int(weights["budget"])),
        "readiness": _readiness_factor(lead_data, cfg, int(weights["readiness"])),
        "urgency": _urgency_factor(lead_data, cfg, int(weights["urgency"]), today),
        "scope": _scope_factor(lead_data, cfg, int(weights["scope"])),
        "area": _area_factor(lead_data, cfg, int(weights["area"])),
    }

    factors = []
    total = 0
    for key in FACTOR_ORDER:
        points, reason = raw_factors[key]
        maximum = int(weights[key])
        points = max(0, min(points, maximum))
        total += points
        factors.append(
            {
                "key": key,
                "label": FACTOR_LABELS[key],
                "points": points,
                "max": maximum,
                "reason": reason,
            }
        )

    total = max(0, min(100, total))
    bands = cfg["bands"]
    if total >= int(bands["hot"]):
        band = "hot"
    elif total >= int(bands["warm"]):
        band = "warm"
    else:
        band = "low"

    summary = "; ".join(f"{item['label']} {item['points']}/{item['max']}" for item in factors)
    return {
        "total": total,
        "band": band,
        "factors": factors,
        "summary": summary,
        "scored_on": today.isoformat(),
    }


def band_label(band: str) -> str:
    return {"hot": "Hot", "warm": "Warm", "low": "Nurture"}.get(band, "Unscored")


def recalculate_score(lead, config, today: date | None = None) -> dict:
    """Recalculate deterministic score for an existing lead."""
    from ..utils import local_today
    result = score_lead(lead.to_scoring_dict(), config, today=today or local_today(config.get("TIMEZONE", "Asia/Kolkata")))
    lead.score = result["total"]
    lead.score_factors = result
    return result
