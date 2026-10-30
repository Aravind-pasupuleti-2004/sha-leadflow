"""Google Gemini free-tier adapter using the supported REST endpoint."""

from __future__ import annotations

import time
from urllib.parse import quote

from .base import (
    AIProvider,
    AIResponseError,
    AIResult,
    parse_json_object,
    post_with_retries,
)

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float,
        max_retries: int,
        logger=None,
        thinking_level: str | None = None,
    ):
        super().__init__(model=model, timeout=timeout, max_retries=max_retries, logger=logger)
        self._api_key = api_key
        allowed_levels = {"minimal", "low", "medium", "high"}
        level = (thinking_level or "").strip().lower()
        self.thinking_level = level if level in allowed_levels else None

    def generate_json(self, system_prompt: str, user_prompt: str, operation: str = "general") -> AIResult:
        generation_config = {
            "temperature": 0.2,
            "maxOutputTokens": 1200,
            "responseMimeType": "application/json",
        }
        if self.thinking_level:
            generation_config["thinkingConfig"] = {"thinkingLevel": self.thinking_level}
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": generation_config,
        }
        headers = {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        started = time.perf_counter()
        response = post_with_retries(
            url=GEMINI_ENDPOINT.format(model=quote(self.model, safe="")),
            headers=headers,
            payload=payload,
            timeout=self.timeout,
            max_retries=self.max_retries,
            logger=self.logger,
            provider=self.name,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        try:
            body = response.json()
        except ValueError as exc:
            raise AIResponseError("invalid_json") from exc

        candidates = body.get("candidates") or []
        if not candidates:
            raise AIResponseError("no_candidates")
        parts = ((candidates[0].get("content") or {}).get("parts")) or []
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        if not text.strip():
            raise AIResponseError("empty_candidate")

        usage = body.get("usageMetadata") or {}
        data = parse_json_object(text)
        return AIResult(
            data=data,
            provider=self.name,
            model=self.model,
            latency_ms=latency_ms,
            prompt_tokens=usage.get("promptTokenCount"),
            completion_tokens=usage.get("candidatesTokenCount"),
        )
