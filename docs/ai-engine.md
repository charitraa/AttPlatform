# ATT Platform — AI Engine

The AI engine (`backend/apps/ai/`) adds classification, priority prediction,
summarisation, routing, response suggestions, a knowledge assistant and operational
insights — while keeping humans in control and the system usable when AI is
unavailable.

## 1. Principles

1. **Provider-independent.** Business logic calls `AIService` capabilities, never a
   vendor SDK.
2. **Explainable.** Every result stores reasoning, confidence, provider, model and
   prompt version.
3. **Advisory by default.** AI produces *recommendations*. Applying them
   automatically is an explicit per-organization policy, and every auto-applied
   change is attributed to `actor_type=ai` in history and can be overridden.
4. **Fail-safe.** Provider failure never blocks ticket creation; the ticket proceeds
   with manual triage and the analysis is marked `failed` with the error.
5. **Honest.** The mock provider's output is flagged `is_mock=true` and labelled
   "Demo AI" in the UI. Nothing pretends to be a real model result.

## 2. Layers

```
views / event handlers
        │
        ▼
apps.ai.services          ← capability functions: classify_ticket(), predict_priority(),
        │                   summarize_ticket(), recommend_routing(), suggest_response(),
        │                   answer_question(), generate_insights()
        │ builds prompt (versioned templates) + context (selectors, org-scoped)
        ▼
apps.ai.client.AIClient   ← retries, timeouts, circuit breaker, JSON-schema validation,
        │                   token/latency accounting, persistence to AIAnalysis
        ▼
apps.ai.providers.base.AIProvider (interface)
   ├── MockProvider              deterministic, rule-based, offline (dev/test/demo)
   ├── AnthropicProvider         Claude via Messages API
   └── OpenAICompatibleProvider  any OpenAI-compatible endpoint (Azure, local vLLM, Ollama…)
```

### Provider interface

```python
class AIProvider(Protocol):
    name: str
    def complete_json(self, *, system: str, prompt: str, schema: dict,
                      model: str | None, max_tokens: int, timeout: float) -> ProviderResult: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...   # optional capability
```

`ProviderResult` carries `data`, `raw_text`, `model`, `tokens_in`, `tokens_out`,
`latency_ms`. Providers raise `AIProviderError` subclasses (`Timeout`, `RateLimited`,
`InvalidResponse`, `Unavailable`) — the client maps those to retry/fail behaviour.

### Configuration

| Variable | Purpose |
|----------|---------|
| `AI_PROVIDER` | `mock` (default) \| `anthropic` \| `openai_compatible` |
| `AI_MODEL` | default model id for the provider |
| `AI_API_KEY` | provider key (server-side only) |
| `AI_BASE_URL` | for OpenAI-compatible endpoints |
| `AI_TIMEOUT_SECONDS`, `AI_MAX_RETRIES` | client behaviour |
| `AI_AUTO_APPLY_MIN_CONFIDENCE` | platform floor for auto-apply |

Organizations may override with an `Integration(kind=llm)` row whose credentials are
encrypted at rest. Keys are never serialised to any API response or log.

## 3. Capabilities

| Capability | Inputs | Output schema (stored in `AIAnalysis.output`) | Human control |
|------------|--------|-----------------------------------------------|---------------|
| Classification | title, description, customer, asset, category list | `category_id`, `department`, `entities` (asset, location, error codes), `confidence`, `reasoning` | Agent accepts/changes category |
| Priority | ticket text, customer tier, asset criticality, SLA policy | `priority`, `confidence`, `reasoning`, `signals[]` | Override requires `ai.override` permission; stored as `overridden` |
| Summarisation | description + public comments + internal notes (staff only) | `summary`, `key_points[]`, `troubleshooting_done[]`, `open_questions[]` | Read-only aid |
| Smart routing | ticket + candidates | `ranked[{user_id, score, factors, explanation}]` | Assign requires approval unless policy = auto |
| Response suggestion | conversation, KB matches | `draft`, `tone`, `cited_articles[]` | Always editable; never auto-sent |
| Knowledge assistant | question, retrieved articles + similar resolved tickets | `answer`, `steps[]`, `sources[]` | Sources always shown |
| Insights | aggregates (not raw PII) over a period | `insights[{type, title, body, evidence}]` | Dismissable |
| Knowledge extraction | closed ticket thread | draft article | Requires review before publish |

### Smart routing is hybrid

The LLM does not pick the assignee alone. A **deterministic scorer** computes a
score per candidate from:

- skill match vs category required skills (weighted by skill level)
- availability (on shift, not on leave, technician status)
- current workload (open tickets / active work orders vs capacity)
- distance from technician location/home base to the service address
- service-area membership
- recent performance on the category (resolution time, reopen rate)

The top-N candidates and their factor breakdown go to the LLM only to produce a
human-readable explanation (and optionally re-rank with stated reasoning). With the
mock provider or on provider failure, the deterministic ranking is still returned —
routing works without an LLM.

### Retrieval for knowledge assistant

Phase 4 uses PostgreSQL full-text search (`search_vector` on articles and resolved
tickets) with ranking. The `embed()` capability plus `pgvector` is the planned
upgrade for semantic retrieval; the retrieval function is behind a `Retriever`
interface so the switch is local.

## 4. Asynchronous processing

- `ticket.created` → `ai.tasks.analyze_ticket(analysis_id)` on queue `ai`.
- Tasks: `acks_late=True`, retry with exponential backoff on `Timeout`/`RateLimited`
  (max `AI_MAX_RETRIES`), no retry on `InvalidResponse` after one repair attempt.
- `input_hash` deduplicates identical re-runs within a short window.
- Completion emits `ai.analysis.completed` → WebSocket push to ticket viewers.
- A circuit breaker (Redis counter) short-circuits to `failed` when a provider has
  repeated failures, protecting queue throughput.

## 5. Prompt management

Prompts live in `apps/ai/prompts/<capability>.py` with a `VERSION` constant. The
version is stored on each analysis so accuracy can be compared across prompt changes.
Outputs are requested as JSON matching a schema and validated before storage;
invalid output gets one repair attempt, then the analysis fails cleanly.

Prompt-injection hygiene: ticket content is wrapped as quoted data, the system
prompt states it is untrusted, outputs are schema-validated, and the model has no
tools that change state — all state changes happen in services after validation.

## 6. Data protection

- Only the minimum fields needed are sent to the provider; internal notes are
  excluded from customer-facing capabilities (response suggestions).
- Insights use aggregates, not raw customer data.
- Organizations can disable AI entirely or per capability (`Organization.settings.ai`).

## 7. Measuring quality

`AIRecommendation.status` gives accuracy signals: accepted, rejected, overridden.
Analytics reports acceptance rate per capability, per prompt version and per
confidence bucket — feeding threshold tuning for auto-apply.

## 8. Mock provider

`MockProvider` is deterministic and offline:

- Classification/priority by keyword rules (e.g. "outage", "down", "fire" →
  critical; category by keyword overlap with category names).
- Summaries by extractive first-sentences.
- Confidence derived from rule strength, capped at 0.75 so it is visibly not a model.
- Every output includes `"is_mock": true` and reasoning prefixed `[mock]`.

It is the default in development and the only provider used in tests.
