from __future__ import annotations

from datetime import timedelta

import pytest

from app.extensions import db
from app.models import FollowUp
from app.services.ai import (
    build_provider,
    generate_followup_draft,
    qualify_lead,
    validate_insight,
)
from app.services.ai.base import (
    AIProvider,
    AIResponseError,
    AIResult,
    AIUnavailable,
)
from app.services.ai.gemini import GeminiProvider
from app.utils import local_today

VALID_INSIGHT = {
    "summary": "A well-qualified full-home interiors enquiry with a clear budget and near-term start.",
    "next_action": "Call today to confirm scope and book a site visit.",
    "readiness": "hot",
    "timeline": "Start requested within 30 days.",
    "scope_notes": "Full home interiors including kitchen and wardrobes.",
    "confidence": 0.82,
}


class FakeProvider(AIProvider):
    name = "gemini"

    def __init__(self, data=None, error=None):
        super().__init__(model="fake-model", timeout=1, max_retries=0)
        self.data = data if data is not None else dict(VALID_INSIGHT)
        self.error = error
        self.system_prompt = ""
        self.user_prompt = ""
        self.operation = ""

    def generate_json(self, system_prompt, user_prompt, operation="general"):
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.operation = operation
        if self.error:
            raise self.error
        return AIResult(
            data=self.data,
            provider=self.name,
            model=self.model,
            latency_ms=17,
            prompt_tokens=120,
            completion_tokens=40,
        )


def test_qualification_uses_provider_without_sending_contact_details(app, make_lead):
    lead = make_lead(
        name="Private Person",
        phone="9000012345",
        email="private.person@example.com",
    )
    provider = FakeProvider()
    result = qualify_lead(
        lead, lead.score_factors, app.config, logger=None, provider=provider
    )
    assert result.provider == "gemini"
    assert result.summary == VALID_INSIGHT["summary"]
    assert result.next_action == VALID_INSIGHT["next_action"]
    assert result.readiness == "hot"
    assert provider.operation == "qualify"
    prompt_blob = provider.system_prompt + "\n" + provider.user_prompt
    assert lead.name not in prompt_blob
    assert lead.phone not in prompt_blob
    assert lead.email not in prompt_blob


def test_invalid_ai_output_falls_back_to_rules(app, make_lead):
    lead = make_lead()
    provider = FakeProvider(data={"summary": "Too short"})
    result = qualify_lead(
        lead, lead.score_factors, app.config, logger=None, provider=provider
    )
    assert result.fallback
    assert result.provider == "fallback"
    assert result.fallback_reason == "invalid_readiness"
    assert "Rule-based summary" in result.summary
    assert result.next_action


def test_provider_failure_falls_back_to_rules(app, make_lead):
    lead = make_lead()
    provider = FakeProvider(error=AIUnavailable("quota_exhausted", status_code=429))
    result = qualify_lead(
        lead, lead.score_factors, app.config, logger=None, provider=provider
    )
    assert result.fallback
    assert result.fallback_reason == "quota_exhausted"
    assert "does not use an AI provider" in result.summary


def test_missing_provider_falls_back_without_network(app, make_lead):
    lead = make_lead()
    result = qualify_lead(lead, lead.score_factors, app.config, logger=None, provider=None)
    assert result.fallback
    assert result.fallback_reason == "provider_not_configured"


def test_validate_insight_rejects_wrong_types():
    with pytest.raises(AIResponseError):
        validate_insight({"summary": "Long enough summary.", "next_action": "Call"})
    with pytest.raises(AIResponseError):
        validate_insight(
            {
                "summary": "Long enough summary.",
                "next_action": "Call",
                "readiness": "extremely-hot",
            }
        )
    normalized = validate_insight(VALID_INSIGHT)
    assert normalized["readiness"] == "hot"
    assert normalized["confidence"] == 0.82


def test_build_provider_never_invents_a_provider(app):
    config = dict(app.config)
    config["AI_PROVIDER"] = "gemini"
    config["GEMINI_API_KEY"] = ""
    assert build_provider(config) is None

    config["AI_PROVIDER"] = "paid-provider"
    config["GEMINI_API_KEY"] = "not-a-real-key"
    assert build_provider(config) is None

    config["AI_PROVIDER"] = "none"
    assert build_provider(config) is None


def test_qualify_route_saves_valid_provider_output(
    auth_client, make_lead, monkeypatch
):
    lead = make_lead()
    deterministic_score = lead.score
    fake = FakeProvider()
    monkeypatch.setattr(
        "app.routes.leads.build_provider", lambda config, logger=None: fake
    )
    response = auth_client.post(f"/leads/{lead.id}/qualify")
    assert response.status_code == 302
    db.session.refresh(lead)
    assert lead.ai_provider == "gemini"
    assert lead.ai_summary == VALID_INSIGHT["summary"]
    assert lead.ai_next_action == VALID_INSIGHT["next_action"]
    assert lead.score == deterministic_score
    assert lead.ai_extracted["confidence"] == 0.82


def test_qualify_route_falls_back_when_provider_unavailable(
    auth_client, make_lead, monkeypatch
):
    lead = make_lead()
    monkeypatch.setattr(
        "app.routes.leads.build_provider", lambda config, logger=None: None
    )
    response = auth_client.post(f"/leads/{lead.id}/qualify", follow_redirects=True)
    assert response.status_code == 200
    db.session.refresh(lead)
    assert lead.ai_provider == "fallback"
    assert lead.ai_summary
    assert b"rule-based insight" in response.data


def test_draft_falls_back_without_provider(app, make_lead, make_followup):
    lead = make_lead(name="Naina Fictional")
    followup = make_followup(lead)
    result = generate_followup_draft(
        lead, followup, app.config, logger=None, provider=None
    )
    assert result.fallback
    assert "Naina" in result.message
    assert "Team SHA Interface Interiors" in result.message


def test_draft_with_provider_keeps_contacts_private(app, make_lead, make_followup):
    lead = make_lead(
        name="Tara Fictional",
        phone="9000077777",
        email="tara.fictional@example.com",
    )
    followup = make_followup(lead)
    fake = FakeProvider(data={"message": "Thank you for sharing the brief. I will confirm the scope and suggest a site visit."})
    result = generate_followup_draft(
        lead, followup, app.config, logger=None, provider=fake
    )
    assert result.provider == "gemini"
    assert result.message.startswith("Hi Tara,")
    prompt_blob = fake.system_prompt + "\n" + fake.user_prompt
    assert lead.phone not in prompt_blob
    assert lead.email not in prompt_blob
    assert lead.name not in prompt_blob


class FakeResponse:
    def __init__(self, status_code, payload, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload


def gemini_body(text):
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}}],
        "usageMetadata": {"promptTokenCount": 99, "candidatesTokenCount": 12},
    }


def test_gemini_retries_quota_and_parses_json(monkeypatch):
    calls = []
    responses = [
        FakeResponse(429, {}, {"Retry-After": "0"}),
        FakeResponse(200, gemini_body('{"summary": "ok", "next_action": "call", "readiness": "hot"}')),
    ]

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return responses.pop(0)

    monkeypatch.setattr("app.services.ai.base.requests.post", fake_post)
    monkeypatch.setattr("app.services.ai.base.time.sleep", lambda seconds: None)
    provider = GeminiProvider("fake-key", "gemini-test", timeout=1, max_retries=2)
    result = provider.generate_json("system", "user", operation="qualify")
    assert result.data["summary"] == "ok"
    assert result.prompt_tokens == 99
    assert result.completion_tokens == 12
    assert len(calls) == 2
    assert calls[0][1]["headers"]["x-goog-api-key"] == "fake-key"


def test_gemini_sends_configured_thinking_level(monkeypatch):
    calls = []

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse(200, gemini_body('{"summary": "ok", "next_action": "call", "readiness": "hot"}'))

    monkeypatch.setattr("app.services.ai.base.requests.post", fake_post)
    provider = GeminiProvider(
        "fake-key",
        "gemini-3.5-flash-lite",
        timeout=1,
        max_retries=0,
        thinking_level="minimal",
    )
    provider.generate_json("system", "user", operation="qualify")
    generation = calls[0][1]["json"]["generationConfig"]
    assert generation["thinkingConfig"] == {"thinkingLevel": "minimal"}
    assert generation["maxOutputTokens"] == 1200


def test_gemini_quota_exhaustion_raises_without_paid_fallback(monkeypatch):
    monkeypatch.setattr(
        "app.services.ai.base.requests.post",
        lambda *args, **kwargs: FakeResponse(429, {}, {"Retry-After": "0"}),
    )
    monkeypatch.setattr("app.services.ai.base.time.sleep", lambda seconds: None)
    provider = GeminiProvider("fake-key", "gemini-test", timeout=1, max_retries=0)
    with pytest.raises(AIUnavailable) as exc_info:
        provider.generate_json("system", "user")
    assert exc_info.value.reason == "quota_exhausted"
    assert exc_info.value.status_code == 429


def test_gemini_invalid_json_raises_response_error(monkeypatch):
    monkeypatch.setattr(
        "app.services.ai.base.requests.post",
        lambda *args, **kwargs: FakeResponse(200, gemini_body("not-json")),
    )
    provider = GeminiProvider("fake-key", "gemini-test", timeout=1, max_retries=0)
    with pytest.raises(AIResponseError):
        provider.generate_json("system", "user")


def test_followup_fixture_sanity(make_lead, make_followup):
    lead = make_lead()
    followup = make_followup(lead, due_date=local_today() + timedelta(days=1))
    assert isinstance(followup, FollowUp)
    assert followup.status == "pending"
