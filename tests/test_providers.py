import json
from urllib.request import Request

import pytest

from agent_replay import providers


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.payload


def test_openai_adapter_sends_server_key_and_normalizes_reported_usage(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-secret")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "choices": [{"message": {"content": "answer"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 7},
            }
        )

    monkeypatch.setattr(providers.urllib.request, "urlopen", fake_urlopen)
    response = providers.call_provider("openai", "question")

    request = captured["request"]
    assert isinstance(request, Request)
    assert request.get_header("Authorization") == "Bearer test-provider-secret"
    assert "test-provider-secret" not in request.full_url
    assert captured["timeout"] == 30
    assert json.loads(request.data) == {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "question"}],
        "max_tokens": 1024,
    }
    assert response.text == "answer"
    assert response.model == "gpt-test"
    assert response.usage == {"input_tokens": 12, "output_tokens": 7}


def test_gemini_key_is_sent_in_header_and_missing_usage_stays_unavailable(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-secret")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        return FakeResponse({"candidates": [{"content": {"parts": [{"text": "done"}]}}]})

    monkeypatch.setattr(providers.urllib.request, "urlopen", fake_urlopen)
    response = providers.call_provider("gemini", "task")

    request = captured["request"]
    assert request.get_header("X-goog-api-key") == "test-gemini-secret"
    assert "test-gemini-secret" not in request.full_url
    assert response.usage is None


def test_provider_rejects_unconfigured_models_and_oversized_prompts(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "configured")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")

    with pytest.raises(ValueError, match="not configured"):
        providers.call_provider("openai", "question", "another-model")
    with pytest.raises(ValueError, match="at most 8000"):
        providers.call_provider("openai", "x" * 8001)


def test_provider_rejects_malformed_success_responses_without_payload_details(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "configured")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    monkeypatch.setattr(
        providers.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse({"choices": []}),
    )

    with pytest.raises(RuntimeError, match="invalid response"):
        providers.call_provider("openai", "question")


def test_provider_catalog_reports_only_usable_model_names(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "not-returned")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    catalog = {item["id"]: item for item in providers.configured_providers()}

    assert catalog["openai"]["configured"] is True
    assert catalog["openai"]["models"] == ["gpt-test"]
    assert catalog["anthropic"]["configured"] is False
    assert catalog["anthropic"]["models"] == []
    assert all("key" not in item for item in catalog.values())
