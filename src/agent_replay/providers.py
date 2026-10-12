"""Optional server-side provider adapters for the AI playground.

Adapters use the standard library so AgentReplay remains usable offline and does
not require provider SDKs until a user explicitly submits a request.
"""

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from agent_replay.config import DEFAULT_MODEL


@dataclass
class ProviderResponse:
    text: str
    provider: str
    model: str
    usage: dict[str, int] | None = None


def configured_providers() -> list[dict[str, Any]]:
    return [
        {"id": "openai", "label": "OpenAI", "configured": bool(os.getenv("OPENAI_API_KEY"))},
        {
            "id": "anthropic",
            "label": "Anthropic",
            "configured": bool(os.getenv("ANTHROPIC_API_KEY")),
        },
        {"id": "gemini", "label": "Google Gemini", "configured": bool(os.getenv("GEMINI_API_KEY"))},
    ]


def _post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Provider request failed ({exc.code}).") from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("Provider request could not be completed.") from None


def call_provider(provider: str, prompt: str, model: str | None = None) -> ProviderResponse:
    if provider == "openai":
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        resolved = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        data = _post(
            "https://api.openai.com/v1/chat/completions",
            {"Authorization": f"Bearer {key}"},
            {"model": resolved, "messages": [{"role": "user", "content": prompt}]},
        )
        usage = data.get("usage")
        return ProviderResponse(data["choices"][0]["message"]["content"], provider, resolved, usage)

    if provider == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured.")
        resolved = model or os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
        data = _post(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": key, "anthropic-version": "2023-06-01"},
            {
                "model": resolved,
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        usage = data.get("usage", {})
        return ProviderResponse(
            data["content"][0]["text"],
            provider,
            resolved,
            {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            },
        )

    if provider == "gemini":
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")
        resolved = model or DEFAULT_MODEL
        data = _post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{resolved}:generateContent?key={key}",
            {},
            {"contents": [{"parts": [{"text": prompt}]}]},
        )
        usage = data.get("usageMetadata", {})
        return ProviderResponse(
            data["candidates"][0]["content"]["parts"][0]["text"],
            provider,
            resolved,
            {
                "input_tokens": usage.get("promptTokenCount", 0),
                "output_tokens": usage.get("candidatesTokenCount", 0),
            },
        )

    raise ValueError("Unsupported provider.")
