"""
Any OpenAI-compatible chat-completions endpoint (self-hosted vLLM/Ollama, Azure
OpenAI, ...). Implemented with the standard library to avoid a vendor dependency.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import (
    AIRequest,
    InvalidResponse,
    ProviderConfigError,
    ProviderResult,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimited,
)


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(self, *, api_key: str, model: str, base_url: str):
        if not base_url or not model:
            raise ProviderConfigError("AI_BASE_URL and AI_MODEL are required for the openai_compatible provider.")
        if not base_url.startswith(("https://", "http://")):
            raise ProviderConfigError("AI_BASE_URL must be an http(s) URL.")
        self.api_key, self.model, self.base_url = api_key, model, base_url.rstrip("/")

    def complete_json(self, request: AIRequest, *, timeout: float) -> ProviderResult:
        body = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": request.capability, "schema": request.schema, "strict": True},
            },
        }
        req = urllib.request.Request(  # noqa: S310 - scheme validated in __init__
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - scheme validated in __init__
                payload = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise RateLimited("Rate limited by provider.") from exc
            if exc.code >= 500:
                raise ProviderUnavailable(f"HTTP {exc.code}") from exc
            raise ProviderConfigError(f"HTTP {exc.code}") from exc
        except TimeoutError as exc:
            raise ProviderTimeout("Provider timed out.") from exc
        except urllib.error.URLError as exc:
            raise ProviderUnavailable(str(exc.reason)) from exc
        try:
            text = payload["choices"][0]["message"]["content"]
            data = json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise InvalidResponse("Provider did not return valid JSON.") from exc
        usage = payload.get("usage") or {}
        return ProviderResult(
            data=data,
            model=payload.get("model", self.model),
            raw_text=text,
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
        )
