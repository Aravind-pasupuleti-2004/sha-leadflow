"""Optional Groq free-tier adapter (OpenAI-compatible JSON chat endpoint)."""

from __future__ import annotations

import time

from .base import (
    AIProvider,
    AIResponseError,
    AIResult,
    parse_json_object,
    post_with_retries,
)

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider(AIProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str, timeout: float, max_retries: int, logger=None):
        super().__init__(model=model, timeout=timeout, max_retries=max_retries, logger=logger)
        self._api_key = api_key

    def generate_json(self, system_prompt: str, user_prompt: str, operation: str = "general") -> AIResult:
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": 800,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        started = time.perf_counter()
        response = post_with_retries(
            url=GROQ_ENDPOINT,
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

        choices = body.get("choices") or []
        if not choices:
            raise AIResponseError("no_choices")
        text = ((choices[0].get("message") or {}).get("content")) or ""
        if not text.strip():
            raise AIResponseError("empty_choice")

        usage = body.get("usage") or {}
        data = parse_json_object(text)
        return AIResult(
            data=data,
            provider=self.name,
            model=self.model,
            latency_ms=latency_ms,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
