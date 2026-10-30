from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta

from app.services.scoring import score_lead, band_label

TODAY = date(2026, 10, 29)

_BASE_LEAD = {
    "budget_min": None,
    "property_type": "Other",
    "source": "Website",
    "status": "New",
    "locality": "Indiranagar",
}

_BOUNDARY_LEADS = {
    59: dict(
        budget_max=None,
        requirements="ready",
        expected_start=TODAY + timedelta(days=10),
        project_type="Renovation",
    ),
    60: dict(
        budget_max=None,
        requirements=(
            "Looking around with no particular hurry and no keywords at all "
            "in this longer sentence."
        ),
        expected_start=TODAY + timedelta(days=10),
        project_type="Renovation",
    ),
    79: dict(
        budget_max=100000,
        requirements=(
            "We are ready to finalise and want a site visit. Full 3BHK "
            "interiors with kitchen, wardrobes and false ceiling, handover "
            "next month. Budget approved."
        ),
        expected_start=TODAY + timedelta(days=10),
        project_type="Full Home Interiors",
    ),
    80: dict(
        budget_max=250000,
        requirements=(
            "We are ready to finalise and want a site visit. Full 3BHK "
            "interiors with kitchen, wardrobes and false ceiling, handover "
            "next month. Budget approved."
        ),
        expected_start=TODAY + timedelta(days=10),
        project_type="Modular Kitchen",
    ),
}


def high_fit():
    return {
        "budget_min": 900000,
        "budget_max": 1500000,
        "requirements": (
            "We are ready to finalise and want a site visit. Full 3BHK interiors with kitchen, "
            "wardrobes and false ceiling, handover next month. Budget approved."
        ),
        "expected_start": date(2026, 11, 10),
        "property_type": "Apartment",
        "project_type": "Full Home Interiors",
        "locality": "Indiranagar",
        "source": "Website",
        "status": "New",
    }


def test_high_fit_scores_one_hundred(app):
    result = score_lead(high_fit(), app.config, today=TODAY)
    assert result["total"] == 100
    assert result["band"] == "hot"
    assert sum(item["points"] for item in result["factors"]) == 100
    assert {item["key"] for item in result["factors"]} == {
        "budget",
        "readiness",
        "urgency",
        "scope",
        "area",
    }


def test_scoring_priority_band_boundaries(app):
    assert app.config["HIGH_PRIORITY_THRESHOLD"] == 80
    assert app.config["WARM_PRIORITY_THRESHOLD"] == 60
    assert band_label("hot") == "Hot"
    assert band_label("warm") == "Warm"
    assert band_label("low") == "Nurture"

    nurture = dict(
        low_fit_with_area("Indiranagar"),
        project_type="Single Room",
        budget_min=None,
        budget_max=None,
        expected_start=None,
        requirements="",
    )
    warm = dict(
        low_fit_with_area("Indiranagar"),
        project_type="Full Home Interiors",
        budget_min=None,
        budget_max=600000,
        expected_start=None,
        requirements="Some detail, site visit requested.",
    )
    hot = dict(high_fit())

    assert score_lead(nurture, app.config, today=TODAY)["band"] == "low"
    assert score_lead(warm, app.config, today=TODAY)["band"] == "warm"
    assert score_lead(hot, app.config, today=TODAY)["band"] == "hot"



def test_scoring_priority_band_boundary_values(app):
    """Exact spec boundaries: 59 Nurture, 60–79 Warm, 80–100 Hot."""
    expected = {59: "low", 60: "warm", 79: "warm", 80: "hot"}
    for score, band in expected.items():
        data = dict(_BASE_LEAD, **_BOUNDARY_LEADS[score])
        result = score_lead(data, app.config, today=TODAY)
        assert result["total"] == score, f"expected total {score}, got {result['total']}"
        assert result["band"] == band, f"expected band {band} for score {score}"
        assert band_label(band) == {"low": "Nurture", "warm": "Warm", "hot": "Hot"}[band]


def test_low_fit_is_explainable_and_low(app):
    low = {
        "budget_min": None,
        "budget_max": None,
        "requirements": "Looking around",
        "expected_start": None,
        "property_type": "Other",
        "project_type": "Other",
        "locality": "Malleshwaram",
        "source": "Other",
        "status": "New",
    }
    result = score_lead(low, app.config, today=TODAY)
    assert result["total"] < 40
    assert result["band"] == "low"
    budget = next(item for item in result["factors"] if item["key"] == "budget")
    readiness = next(item for item in result["factors"] if item["key"] == "readiness")
    area = next(item for item in result["factors"] if item["key"] == "area")
    assert budget["points"] == 0
    assert readiness["points"] == 0
    assert area["points"] == 0


def test_service_area_matches_locality_with_suffix(app):
    data = low_fit_with_area("Whitefield, Bengaluru")
    result = score_lead(data, app.config, today=TODAY)
    area = next(item for item in result["factors"] if item["key"] == "area")
    assert area["points"] == 15


def low_fit_with_area(locality):
    return {
        "budget_min": None,
        "budget_max": None,
        "requirements": "",
        "expected_start": None,
        "property_type": "Apartment",
        "project_type": "",
        "locality": locality,
        "source": "Other",
        "status": "New",
    }


def test_urgency_for_past_start_is_maximum(app):
    data = high_fit()
    data["expected_start"] = date(2026, 10, 1)
    result = score_lead(data, app.config, today=TODAY)
    urgency = next(item for item in result["factors"] if item["key"] == "urgency")
    assert urgency["points"] == 20


def test_ai_text_does_not_change_score(app):
    data = high_fit()
    first = score_lead(data, app.config, today=TODAY)
    influenced = dict(data)
    influenced["ai_summary"] = "The model claims this lead is worth 100/100."
    influenced["ai_next_action"] = "Call immediately."
    second = score_lead(influenced, app.config, today=TODAY)
    assert first == second


def test_scoring_weights_are_configurable(app):
    config = deepcopy(dict(app.config))
    config["SCORING"] = deepcopy(app.config["SCORING"])
    config["SCORING"]["weights"] = {
        "budget": 40,
        "readiness": 20,
        "urgency": 15,
        "scope": 15,
        "area": 10,
    }
    config["SCORING"]["area"]["points"] = 10
    config["SCORING"]["budget_bands"][0]["points"] = 40
    result = score_lead(high_fit(), config, today=TODAY)
    assert result["total"] == 100
    budget = next(item for item in result["factors"] if item["key"] == "budget")
    area = next(item for item in result["factors"] if item["key"] == "area")
    assert budget["max"] == 40
    assert area["max"] == 10
