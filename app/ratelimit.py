"""A tiny in-process rate limiter.

This is intentionally dependency-free. It protects a single process from
accidental bursts; it is not a distributed quota system. The limits reset on
restart and are not shared between Gunicorn workers. For this free-tier,
single-instance deployment that is an acceptable trade-off and is documented
in the README.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import abort, current_app, request


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            if len(self._hits) > 5000:
                for stale_key in [k for k, v in self._hits.items() if not v]:
                    self._hits.pop(stale_key, None)
            return True


limiter = InMemoryRateLimiter()


def rate_limit(scope: str, config_key: str, methods: tuple[str, ...] = ("POST",)):
    """Limit requests per client IP, reading the numeric limit from config."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if request.method not in methods or not current_app.config.get("RATELIMIT_ENABLED", True):
                return view(*args, **kwargs)
            limit = int(current_app.config.get(config_key, 10))
            client = request.remote_addr or "unknown"
            if not limiter.allow(f"{scope}:{client}", limit):
                abort(429)
            return view(*args, **kwargs)

        return wrapped

    return decorator
