"""Claude via the official Anthropic SDK, using structured outputs for schema-valid JSON."""

from __future__ import annotations

import json

import anthropic

from .base import (
    AIRequest,
    InvalidResponse,
    ProviderConfigError,
    ProviderResult,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimited,
    Refused,
)

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, *, api_key: str, model: str = "", base_url: str = "", client=None):
        if not api_key and client is None:
            raise ProviderConfigError("AI_API_KEY is required for the Anthropic provider.")
        self.model = model or DEFAULT_MODEL
        # SDK retries are disabled: apps.ai.client owns retries and the circuit breaker.
        self.client = client or anthropic.Anthropic(api_key=api_key, base_url=base_url or None, max_retries=0)

    def complete_json(self, request: AIRequest, *, timeout: float) -> ProviderResult:
        try:
            response = self.client.with_options(timeout=timeout).beta.messages.create(
                model=self.model,
                max_tokens=request.max_tokens,
                system=request.system,
                messages=[{"role": "user", "content": request.prompt}],
                output_config={
                    "effort": request.effort,
                    "format": {"type": "json_schema", "schema": request.schema},
                },
                # If a safety classifier declines, the API retries on a fallback model in the same call.
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.APITimeoutError as exc:
            raise ProviderTimeout(str(exc)) from exc
        except anthropic.RateLimitError as exc:
            raise RateLimited(str(exc)) from exc
        except (
            anthropic.AuthenticationError,
            anthropic.PermissionDeniedError,
            anthropic.NotFoundError,
            anthropic.BadRequestError,
        ) as exc:
            raise ProviderConfigError(f"{exc.__class__.__name__}: {getattr(exc, 'message', exc)}") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderUnavailable(f"HTTP {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderUnavailable(str(exc)) from exc

        if response.stop_reason == "refusal":
            category = getattr(getattr(response, "stop_details", None), "category", None)
            raise Refused(f"The model declined this request (category: {category or 'unspecified'}).")
        if response.stop_reason == "max_tokens":
            raise InvalidResponse("The response was cut off before completing (max_tokens).")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InvalidResponse("The model did not return valid JSON.") from exc
        usage = getattr(response, "usage", None)
        return ProviderResult(
            data=data,
            model=getattr(response, "model", self.model),
            raw_text=text,
            tokens_in=getattr(usage, "input_tokens", None),
            tokens_out=getattr(usage, "output_tokens", None),
        )
