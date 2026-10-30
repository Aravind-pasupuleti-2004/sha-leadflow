"""Register application blueprints."""

from . import auth, dashboard, followups, health, leads

__all__ = ["auth", "dashboard", "followups", "health", "leads"]
