"""Common AI provider interface and HTTP retry helpers.

The application only talks to free-tier providers (Gemini by default, Groq
optionally). There is no paid-provider fallback: if the configured provider is
unavailable, deterministic rule-based text is used instead.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import requests


class AIUnavailable(RuntimeError):
    """The provider could not be reached or returned an unusable response."""

    def __init__(self, reason: str, status_code: int | None = None, retryable: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code
        self.retryable = retryable


class AIResponseError(AIUnavailable):
    """The provider responded, but the payload failed validation."""


@dataclass
class AIResult:
    data: dict
    provider: str
    model: str
    latency_ms: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class AIProvider(ABC):
    name = "unknown"

    def __init__(self, model: str, timeout: float, max_retries: int, logger=None):
        self.model = model
        self.timeout = timeout
        self.max_retries = max(0, min(int(max_retries), 3))
        self.logger = logger

    @abstractmethod
    def generate_json(self, system_prompt: str, user_prompt: str, operation: str = "general") -> AIResult:
        raise NotImplementedError


def parse_json_object(text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise AIResponseError("empty_response")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        value = json.loads(cleaned)
    except (ValueError, TypeError):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end <= start:
            raise AIResponseError("invalid_json")
        try:
            value = json.loads(cleaned[start : end + 1])
        except (ValueError, TypeError) as exc:
            raise AIResponseError("invalid_json") from exc
    if not isinstance(value, dict):
        raise AIResponseError("not_an_object")
    return value


def post_with_retries(
    *,
    url: str,
    headers: dict[str, str],
    payload: dict,
    timeout: float,
    max_retries: int,
    logger=None,
    provider: str,
) -> requests.Response:
    """POST with bounded retries for timeouts, 429, and 5xx responses.

    URL, headers, and response bodies are never logged here because headers can
    contain API keys.
    """
    last_error: AIUnavailable | None = None
    attempts = max(0, min(int(max_retries), 3)) + 1
    for attempt in range(attempts):
        response = None
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
        except requests.Timeout:
            last_error = AIUnavailable("timeout", retryable=True)
        except requests.RequestException:
            last_error = AIUnavailable("network_error", retryable=True)
        else:
            if response.status_code == 429:
                last_error = AIUnavailable("quota_exhausted", status_code=429, retryable=True)
            elif response.status_code in (401, 403):
                raise AIUnavailable("auth_failed", status_code=response.status_code)
            elif response.status_code == 400:
                raise AIUnavailable("bad_request", status_code=400)
            elif response.status_code >= 500:
                last_error = AIUnavailable(
                    "provider_server_error", status_code=response.status_code, retryable=True
                )
            elif 200 <= response.status_code < 300:
                return response
            else:
                raise AIUnavailable(
                    f"http_{response.status_code}", status_code=response.status_code
                )

        if attempt < attempts - 1:
            delay = min(4.0, 0.7 * (2**attempt))
            retry_after = None
            if response is not None:
                retry_after = response.headers.get("Retry-After")
            if retry_after and str(retry_after).isdigit():
                delay = min(5.0, max(delay, float(retry_after)))
            if logger:
                logger.warning(
                    "ai_retry provider=%s reason=%s attempt=%s",
                    provider,
                    last_error.reason if last_error else "unknown",
                    attempt + 1,
                )
            time.sleep(delay)

    if last_error is None:  # pragma: no cover - defensive
        last_error = AIUnavailable("unknown_error")
    raise last_error


__all__ = [
    "AIProvider",
    "AIResponseError",
    "AIResult",
    "AIUnavailable",
    "post_with_retries",
    "parse_json_object",
]
