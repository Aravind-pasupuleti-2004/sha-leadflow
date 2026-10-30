"""Environment-based configuration for SHA LeadFlow AI.

All secrets are read from the environment. The defaults in this file are safe
for local development only; production refuses to start with the development
fallback secret.
"""

from __future__ import annotations

import copy
import json
import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DEV_SECRET = "dev-only-secret-change-me"

LEAD_STATUSES = ["New", "Contacted", "Qualified", "Proposal Sent", "Won", "Lost"]
LEAD_SOURCES = ["Website", "Instagram", "Referral", "Walk-in", "Google", "WhatsApp", "Other"]
PROPERTY_TYPES = ["Apartment", "Villa", "Independent House", "Office", "Retail", "Other"]
PROJECT_TYPES = [
    "Full Home Interiors",
    "Renovation",
    "Modular Kitchen",
    "Wardrobes",
    "Single Room",
    "Other",
]

DEFAULT_SERVICE_AREAS = [
    "Indiranagar",
    "Koramangala",
    "HSR Layout",
    "Whitefield",
    "Jayanagar",
    "JP Nagar",
    "Hebbal",
    "Sarjapur Road",
    "Electronic City",
    "Yelahanka",
]

# Deterministic business rules. These weights are an explicit product decision,
# not a model trained on conversion data.
DEFAULT_SCORING = {
    "weights": {
        "budget": 25,
        "readiness": 25,
        "urgency": 20,
        "scope": 15,
        "area": 15,
    },
    "budget_bands": [
        {"min": 1_000_000, "points": 25, "label": "₹10 lakh and above"},
        {"min": 500_000, "points": 18, "label": "₹5–10 lakh"},
        {"min": 250_000, "points": 10, "label": "₹2.5–5 lakh"},
        {"min": 100_000, "points": 4, "label": "₹1–2.5 lakh"},
    ],
    "readiness": {
        "detailed_length": 80,
        "some_length": 30,
        "detailed_requirements": 8,
        "some_requirements": 4,
        "intent_keyword": 7,
        "timeline_shared": 5,
        "budget_shared": 5,
        "keywords": [
            "ready",
            "immediate",
            "urgent",
            "move in",
            "moving in",
            "handover",
            "finalise",
            "finalize",
            "budget approved",
            "site visit",
            "quotation",
            "quote",
        ],
    },
    "urgency": {
        "bands": [
            {"days": 30, "points": 20},
            {"days": 60, "points": 16},
            {"days": 90, "points": 12},
            {"days": 180, "points": 8},
            {"days": 365, "points": 4},
        ],
        "far_future": 2,
        "unknown": 2,
        "keyword": 12,
        "keywords": ["urgent", "immediate", "asap", "move in", "moving in", "handover"],
    },
    "scope": {
        "projects": {
            "Full Home Interiors": 15,
            "Renovation": 12,
            "Modular Kitchen": 10,
            "Wardrobes": 8,
            "Single Room": 6,
        },
        "default": 2,
    },
    "area": {"points": 15},
    "bands": {"hot": 80, "warm": 60},
    "high_priority_threshold": 80,
    "warm_priority_threshold": 60,
    "service_areas": DEFAULT_SERVICE_AREAS,
}


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise RuntimeError(f"{name} must be an integer") from exc
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def env_float(name: str, default: float, minimum: float = 0.1, maximum: float = 60.0) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        value = default
    else:
        try:
            value = float(raw)
        except ValueError as exc:
            raise RuntimeError(f"{name} must be a number") from exc
    return min(maximum, max(minimum, value))


def normalize_database_url(url: str) -> str:
    """Return a SQLAlchemy 2.x URL using the psycopg 3 driver.

    Render historically supplied ``postgres://`` URLs; Supabase supplies
    ``postgresql://`` URLs. Both are mapped to ``postgresql+psycopg://``.
    """
    url = (url or "").strip()
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def _deep_merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_scoring_config() -> dict:
    scoring = copy.deepcopy(DEFAULT_SCORING)

    raw_json = os.environ.get("SCORING_CONFIG_JSON", "").strip()
    if raw_json:
        try:
            overrides = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError("SCORING_CONFIG_JSON is not valid JSON") from exc
        if not isinstance(overrides, dict):
            raise RuntimeError("SCORING_CONFIG_JSON must be a JSON object")
        _deep_merge(scoring, overrides)

    service_areas = os.environ.get("SERVICE_AREAS", "").strip()
    if service_areas:
        scoring["service_areas"] = [area.strip() for area in service_areas.split(",") if area.strip()]

    threshold_raw = os.environ.get("HIGH_PRIORITY_THRESHOLD", "").strip()
    if threshold_raw:
        try:
            scoring["high_priority_threshold"] = min(100, max(0, int(threshold_raw)))
        except ValueError as exc:
            raise RuntimeError("HIGH_PRIORITY_THRESHOLD must be an integer") from exc

    weights = scoring.get("weights", {})
    required = {"budget", "readiness", "urgency", "scope", "area"}
    if not isinstance(weights, dict) or not required.issubset(weights):
        raise RuntimeError("SCORING_CONFIG_JSON must define all five weights")
    if any(not isinstance(v, int) or v < 0 for v in weights.values()):
        raise RuntimeError("Scoring weights must be non-negative integers")
    if sum(weights.values()) != 100:
        raise RuntimeError("Scoring weights must add up to 100")
    if not isinstance(scoring.get("service_areas"), list):
        raise RuntimeError("service_areas must be a list")
    return scoring


class Config:
    APP_NAME = "SHA LeadFlow AI"
    APP_ENV = os.environ.get("APP_ENV", "development").lower()
    SECRET_KEY = os.environ.get("SECRET_KEY", DEV_SECRET)
    PREFERRED_URL_SCHEME = "https" if APP_ENV == "production" else "http"

    SQLALCHEMY_DATABASE_URI = normalize_database_url(
        os.environ.get(
            "DATABASE_URL",
            f"sqlite:///{(BASE_DIR / 'instance' / 'sha_leadflow.db').as_posix()}",
        )
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }

    MAX_CONTENT_LENGTH = 6 * 1024 * 1024  # hard request cap (6 MiB)
    MAX_CSV_BYTES = env_int(
        "MAX_CSV_BYTES", 2 * 1024 * 1024, minimum=1024, maximum=5 * 1024 * 1024
    )
    MAX_CSV_ROWS = env_int("MAX_CSV_ROWS", 1000, minimum=1, maximum=5000)

    WTF_CSRF_TIME_LIMIT = 2 * 60 * 60  # seconds; flask-wtf passes this to itsdangerous
    WTF_CSRF_SSL_STRICT = True

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", False)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    REMEMBER_COOKIE_HTTPONLY = True

    RATELIMIT_ENABLED = env_bool("RATELIMIT_ENABLED", True)
    LOGIN_RATE_LIMIT_PER_MINUTE = env_int("LOGIN_RATE_LIMIT_PER_MINUTE", 10, 1, 120)
    LEAD_RATE_LIMIT_PER_MINUTE = env_int("LEAD_RATE_LIMIT_PER_MINUTE", 20, 1, 300)
    AI_RATE_LIMIT_PER_MINUTE = env_int("AI_RATE_LIMIT_PER_MINUTE", 10, 1, 120)

    AI_PROVIDER = os.environ.get("AI_PROVIDER", "gemini").strip().lower()
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "").strip()
    GEMINI_THINKING_LEVEL = os.environ.get("GEMINI_THINKING_LEVEL", "minimal").strip().lower()
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
    GROQ_MODEL = os.environ.get("GROQ_MODEL", "").strip()
    AI_TIMEOUT_SECONDS = env_float("AI_TIMEOUT_SECONDS", 15.0, 2.0, 60.0)
    AI_MAX_RETRIES = env_int("AI_MAX_RETRIES", 2, 0, 3)

    SCORING = load_scoring_config()
    HIGH_PRIORITY_THRESHOLD = SCORING["bands"]["hot"]
    WARM_PRIORITY_THRESHOLD = SCORING["bands"]["warm"]
    SERVICE_AREAS = SCORING["service_areas"]

    LEAD_STATUSES = LEAD_STATUSES
    LEAD_SOURCES = LEAD_SOURCES
    PROPERTY_TYPES = PROPERTY_TYPES
    PROJECT_TYPES = PROJECT_TYPES

    TIMEZONE = "Asia/Kolkata"
    TRUST_PROXY = env_bool("TRUST_PROXY", False)
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
    DESIRED_PAGE_SIZE = 20


class DevelopmentConfig(Config):
    APP_ENV = "development"


class ProductionConfig(Config):
    APP_ENV = "production"
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", True)
    PREFERRED_URL_SCHEME = "https"
    TRUST_PROXY = env_bool("TRUST_PROXY", True)


class TestingConfig(Config):
    APP_ENV = "testing"
    TESTING = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    AI_PROVIDER = "none"
    GEMINI_API_KEY = ""
    GROQ_API_KEY = ""
    SESSION_COOKIE_SECURE = False
    PREFERRED_URL_SCHEME = "http"
    SERVER_NAME = None


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config(name: str | None = None):
    name = (name or os.environ.get("APP_ENV") or os.environ.get("FLASK_ENV") or "development").lower()
    if name not in CONFIG_MAP:
        name = "production" if name in {"prod", "production"} else "development"
    return CONFIG_MAP[name]
