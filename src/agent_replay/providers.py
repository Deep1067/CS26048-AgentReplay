"""Optional server-side provider adapters for the AI playground and live runs."""

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from agent_replay.config import DEFAULT_MODEL

_PROVIDER_SETTINGS = {
    "openai": ("OPENAI_API_KEY", "OPENAI_MODEL", "gpt-4o-mini"),
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
    "gemini": ("GEMINI_API_KEY", "DEFAULT_MODEL", DEFAULT_MODEL),
}
_PROVIDER_TIMEOUT_SECONDS = 30
_MAX_PROMPT_CHARS = 8000


@dataclass
class ProviderResponse:
    text: str
    provider: str
    model: str
    usage: dict[str, int | None] | None = None


def configured_providers() -> list[dict[str, Any]]:
    labels = {"openai": "OpenAI", "anthropic": "Anthropic", "gemini": "Google Gemini"}
    providers = []
    for provider, (key_name, model_name, default_model) in _PROVIDER_SETTINGS.items():
        configured = bool(os.getenv(key_name))
        model = os.getenv(model_name, default_model).strip()
        providers.append(
            {
                "id": provider,
                "label": labels[provider],
                "configured": configured,
                "models": [model] if configured and model else [],
            }
        )
    return providers


def _post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_PROVIDER_TIMEOUT_SECONDS) as response:
            try:
                data = json.loads(response.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise RuntimeError("Provider returned an invalid response.") from None
            if not isinstance(data, dict):
                raise RuntimeError("Provider returned an invalid response.")
            return data
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Provider request failed ({exc.code}).") from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("Provider request could not be completed.") from None


def _resolve_model(provider: str, requested_model: str | None) -> tuple[str, str]:
    try:
        key_name, model_name, default_model = _PROVIDER_SETTINGS[provider]
    except KeyError:
        raise ValueError("Unsupported provider.") from None
    if not os.getenv(key_name):
        raise RuntimeError(f"{key_name} is not configured.")
    resolved = os.getenv(model_name, default_model).strip()
    if not resolved:
        raise RuntimeError(f"No model is configured for {provider}.")
    if requested_model and requested_model != resolved:
        raise ValueError(
            f"Model '{requested_model}' is not configured for {provider}; "
            "select the configured model or leave model blank."
        )
    return key_name, resolved


def _usage_count(usage: Any, *keys: str) -> int | None:
    if not isinstance(usage, dict):
        return None
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


def call_provider(provider: str, prompt: str, model: str | None = None) -> ProviderResponse:
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Prompt cannot be empty.")
    if len(prompt) > _MAX_PROMPT_CHARS:
        raise ValueError(f"Prompt must be at most {_MAX_PROMPT_CHARS} characters.")
    key_name, resolved = _resolve_model(provider, model)
    key = os.getenv(key_name, "")

    if provider == "openai":
        data = _post(
            "https://api.openai.com/v1/chat/completions",
            {"Authorization": f"Bearer {key}"},
            {
                "model": resolved,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1024,
            },
        )
        raw_usage = data.get("usage") or {}
        usage = {
            "input_tokens": _usage_count(raw_usage, "prompt_tokens"),
            "output_tokens": _usage_count(raw_usage, "completion_tokens"),
        }
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError("Provider returned an invalid response.") from None
        if not isinstance(text, str):
            raise RuntimeError("Provider returned an invalid response.")
        return ProviderResponse(
            text,
            provider,
            resolved,
            usage if any(value is not None for value in usage.values()) else None,
        )

    if provider == "anthropic":
        data = _post(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": key, "anthropic-version": "2023-06-01"},
            {
                "model": resolved,
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        raw_usage = data.get("usage", {})
        usage = {
            "input_tokens": _usage_count(raw_usage, "input_tokens"),
            "output_tokens": _usage_count(raw_usage, "output_tokens"),
        }
        try:
            text = data["content"][0]["text"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError("Provider returned an invalid response.") from None
        if not isinstance(text, str):
            raise RuntimeError("Provider returned an invalid response.")
        return ProviderResponse(
            text,
            provider,
            resolved,
            usage if any(value is not None for value in usage.values()) else None,
        )

    if provider == "gemini":
        data = _post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{resolved}:generateContent",
            {"x-goog-api-key": key},
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 1024},
            },
        )
        raw_usage = data.get("usageMetadata", {})
        usage = {
            "input_tokens": _usage_count(raw_usage, "promptTokenCount"),
            "output_tokens": _usage_count(raw_usage, "candidatesTokenCount"),
        }
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError("Provider returned an invalid response.") from None
        if not isinstance(text, str):
            raise RuntimeError("Provider returned an invalid response.")
        return ProviderResponse(
            text,
            provider,
            resolved,
            usage if any(value is not None for value in usage.values()) else None,
        )

    raise ValueError("Unsupported provider.")
