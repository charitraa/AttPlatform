"""
The one path every AI call takes: provider selection, timeouts, retries with
backoff, schema validation (with a single repair attempt), a circuit breaker, and
persistence of the outcome on `AIAnalysis`. A provider failure never raises into
business code; the analysis is marked `failed` with a readable error.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from decimal import Decimal

import jsonschema
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .models import AIAnalysis
from .prompts import SPECS, build_prompt
from .providers import get_providers
from .providers.base import AIProviderError, AIRequest, InvalidResponse, ProviderConfigError, Refused

logger = logging.getLogger(__name__)

BREAKER_THRESHOLD = 5  # consecutive failures before the breaker opens
BREAKER_COOLDOWN = 60  # seconds the breaker stays open


def input_hash(capability: str, context: dict) -> str:
    payload = json.dumps({"c": capability, "v": SPECS[capability].version, "ctx": context}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _breaker_key(provider: str) -> str:
    return f"ai:breaker:{provider}"


def _breaker_open(provider: str) -> bool:
    return (cache.get(_breaker_key(provider)) or 0) >= BREAKER_THRESHOLD


def _record_failure(provider: str) -> None:
    key = _breaker_key(provider)
    cache.add(key, 0, BREAKER_COOLDOWN)
    try:
        cache.incr(key)
    except ValueError:  # key expired between add and incr
        cache.set(key, 1, BREAKER_COOLDOWN)


def _record_success(provider: str) -> None:
    cache.delete(_breaker_key(provider))


def run(analysis: AIAnalysis, capability: str, context: dict) -> AIAnalysis:
    """Execute `capability` for an existing pending analysis and persist the result."""
    spec = SPECS[capability]
    analysis.status = AIAnalysis.Status.RUNNING
    analysis.prompt_version = spec.version
    analysis.save(update_fields=["status", "prompt_version", "updated_at"])

    started = time.monotonic()
    try:
        providers = get_providers()
    except ProviderConfigError as exc:
        return _fail(analysis, f"AI is not configured: {exc}", started)

    request = AIRequest(
        capability=capability,
        system=spec.system,
        prompt=build_prompt(capability, context),
        schema=spec.schema,
        context=context,
        effort=spec.effort,
    )
    errors: list[str] = []
    total_attempts = 0
    for provider in providers:  # primary first, then each fallback
        analysis.provider = provider.name
        if _breaker_open(provider.name):
            errors.append(f"{provider.name}: temporarily unavailable (too many recent failures)")
            continue
        result, error, attempts = _attempt(provider, request, spec)
        total_attempts += attempts
        if result is not None:
            _record_success(provider.name)
            analysis.attempts = total_attempts
            return _complete(analysis, result, started)
        if error.retryable:
            _record_failure(provider.name)  # only infrastructure failures count towards the breaker
        errors.append(f"{provider.name}: {error.__class__.__name__}: {error}")
        if isinstance(error, Refused):  # a refusal is respected, not shopped around to another model
            break
    analysis.attempts = total_attempts
    return _fail(analysis, " | ".join(errors) or "No AI provider available.", started)


def _attempt(provider, request: AIRequest, spec):
    """Retries one provider. Returns (result, None, attempts) or (None, last_error, attempts)."""
    retries_left = settings.AI_MAX_RETRIES  # extra attempts for transient errors (timeouts, 429, 5xx)
    repair_used = False  # malformed output gets exactly one more attempt
    attempt = 0
    while True:
        attempt += 1
        try:
            result = provider.complete_json(request, timeout=settings.AI_TIMEOUT_SECONDS)
            jsonschema.validate(result.data, spec.schema)
        except jsonschema.ValidationError as exc:
            error: AIProviderError = InvalidResponse(f"Output did not match the schema: {exc.message}")
        except AIProviderError as exc:
            error = exc
        else:
            return result, None, attempt
        if isinstance(error, InvalidResponse) and not repair_used:
            repair_used = True
            continue
        if error.retryable and retries_left > 0:
            retries_left -= 1
            time.sleep(min(8.0, settings.AI_RETRY_BACKOFF_SECONDS * 2 ** (attempt - 1)))
            continue
        return None, error, attempt


def _complete(analysis: AIAnalysis, result, started: float) -> AIAnalysis:
    data = result.data
    confidence = data.get("confidence")
    analysis.status = AIAnalysis.Status.COMPLETED
    analysis.output = data
    analysis.model = result.model
    analysis.is_mock = result.is_mock
    analysis.confidence = Decimal(str(round(float(confidence), 3))) if isinstance(confidence, (int, float)) else None
    analysis.reasoning = str(data.get("reasoning", ""))[:5000]
    analysis.tokens_in, analysis.tokens_out = result.tokens_in, result.tokens_out
    analysis.latency_ms = int((time.monotonic() - started) * 1000)
    analysis.error = ""
    analysis.completed_at = timezone.now()
    analysis.save()
    return analysis


def _fail(analysis: AIAnalysis, error: str, started: float) -> AIAnalysis:
    logger.warning("AI %s failed for analysis %s: %s", analysis.kind, analysis.id, error)
    analysis.status = AIAnalysis.Status.FAILED
    analysis.error = error[:500]
    analysis.latency_ms = int((time.monotonic() - started) * 1000)
    analysis.completed_at = timezone.now()
    analysis.save()
    return analysis
