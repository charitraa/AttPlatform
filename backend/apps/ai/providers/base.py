"""
Provider-independent AI interface. Business logic never imports a vendor SDK; it
builds an `AIRequest` and gets back a validated `ProviderResult`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class AIProviderError(Exception):
    """Base class. `retryable` tells the client whether another attempt may succeed."""

    retryable = False


class ProviderTimeout(AIProviderError):
    retryable = True


class RateLimited(AIProviderError):
    retryable = True


class ProviderUnavailable(AIProviderError):
    retryable = True


class InvalidResponse(AIProviderError):
    """The model answered, but not with JSON matching the schema."""


class Refused(AIProviderError):
    """The model declined the request (e.g. a safety refusal)."""


class ProviderConfigError(AIProviderError):
    """Bad credentials, unknown model, malformed request: fix configuration, don't retry."""


@dataclass(frozen=True)
class AIRequest:
    capability: str
    system: str
    prompt: str
    schema: dict
    # Structured inputs. Real providers only see `prompt`; the mock provider uses
    # `context` directly so its output is deterministic.
    context: dict = field(default_factory=dict)
    effort: str = "low"  # low | medium | high
    max_tokens: int = 16000


@dataclass
class ProviderResult:
    data: dict[str, Any]
    model: str
    raw_text: str = ""
    tokens_in: int | None = None
    tokens_out: int | None = None
    is_mock: bool = False


class AIProvider(Protocol):
    name: str

    def complete_json(self, request: AIRequest, *, timeout: float) -> ProviderResult: ...
