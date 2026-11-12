"""
Deterministic, offline provider for development, demos and tests.

It never pretends to be a model: confidence is capped at 0.75, every reasoning
string starts with "[mock]", and results are stored with `is_mock=True` so the UI
labels them as demo output.
"""

from __future__ import annotations

import re
from collections import Counter

from .base import AIRequest, ProviderResult

MAX_CONFIDENCE = 0.75

CRITICAL_WORDS = {
    "outage",
    "down",
    "offline",
    "fire",
    "smoke",
    "flood",
    "alarm",
    "stock at risk",
    "patient",
    "spo2",
    "server room",
    "not starting",
    "failed",
    "failure",
}
HIGH_WORDS = {"urgent", "asap", "not cooling", "trips", "tripping", "rejecting", "warm", "leak", "error", "cannot"}
LOW_WORDS = {"question", "how do i", "request", "slow", "minor", "cosmetic", "when convenient"}

DEPARTMENT_HINTS = {
    "IT": {"network", "wifi", "wi-fi", "switch", "printer", "scan", "email", "server", "laptop"},
    "Facilities": {"ac", "hvac", "cooling", "generator", "power", "breaker", "compressor", "cold room", "light"},
    "Biomedical": {"patient", "monitor", "spo2", "ventilator", "medical"},
    "Security": {"badge", "door", "access", "camera", "reader"},
}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9][a-z0-9-]*", text.lower()))


def _text(ctx: dict) -> str:
    return f"{ctx.get('title', '')} {ctx.get('description', '')}".lower()


def _conf(score: float) -> float:
    return round(min(MAX_CONFIDENCE, max(0.2, score)), 2)


def _first_sentences(text: str, n: int = 2) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(parts[:n]).strip()


class MockProvider:
    name = "mock"
    model = "mock-rules-v1"

    def complete_json(self, request: AIRequest, *, timeout: float) -> ProviderResult:
        handler = getattr(self, f"_{request.capability}")
        return ProviderResult(data=handler(request.context), model=self.model, is_mock=True)

    # ------------------------------------------------------------------ triage
    def _classification(self, ctx: dict) -> dict:
        text, words = _text(ctx), _words(_text(ctx))
        best, best_score = None, 0.0
        for cat in ctx.get("categories", []):
            cat_words = _words(f"{cat['name']} {cat.get('department', '')} {cat.get('description', '')}")
            overlap = len(cat_words & words) + (2 if cat["name"].lower() in text else 0)
            if overlap > best_score:
                best, best_score = cat, overlap
        department = best.get("department") if best else ""
        if not department:
            department = (
                max(DEPARTMENT_HINTS, key=lambda d: len(DEPARTMENT_HINTS[d] & words))
                if any(DEPARTMENT_HINTS[d] & words for d in DEPARTMENT_HINTS)
                else ""
            )
        codes = sorted(set(re.findall(r"\b(?:e|err|error)[- ]?\d{2,4}\b", text)))
        return {
            "category_id": best["id"] if best else None,
            "department": department or "General",
            "entities": {"error_codes": codes, "location": None, "asset_hint": ctx.get("asset_name")},
            "confidence": _conf(0.3 + 0.15 * best_score) if best else 0.2,
            "reasoning": (
                f"[mock] Matched keywords for '{best['name']}'."
                if best
                else "[mock] No category keywords matched the ticket text."
            ),
        }

    def _priority(self, ctx: dict) -> dict:
        text = _text(ctx)
        signals = [w for w in sorted(CRITICAL_WORDS) if w in text]
        if signals:
            priority, score = (
                "critical" if len(signals) > 1 or ctx.get("customer_tier") == "enterprise" else "high",
                0.55,
            )
        else:
            signals = [w for w in sorted(HIGH_WORDS) if w in text]
            if signals:
                priority, score = "high", 0.5
            else:
                signals = [w for w in sorted(LOW_WORDS) if w in text]
                priority, score = ("low", 0.45) if signals else ("medium", 0.35)
        if ctx.get("customer_tier") == "enterprise":
            signals.append("enterprise customer")
        return {
            "priority": priority,
            "confidence": _conf(score + 0.05 * len(signals)),
            "signals": signals[:6],
            "reasoning": f"[mock] Keyword rules suggest {priority}"
            + (f" (signals: {', '.join(signals[:4])})." if signals else "."),
        }

    # ----------------------------------------------------------------- writing
    def _summary(self, ctx: dict) -> dict:
        comments = ctx.get("comments", [])
        done = [_first_sentences(c["body"], 1) for c in comments if c.get("author_is_staff")][:4]
        questions = [_first_sentences(c["body"], 1) for c in comments if "?" in c["body"]][:3]
        return {
            "summary": f"[mock] {_first_sentences(ctx.get('description', ''), 2)}",
            "key_points": [
                f"Status: {ctx.get('status')}",
                f"Priority: {ctx.get('priority')}",
                f"{len(comments)} message(s) so far",
            ],
            "troubleshooting_done": done,
            "open_questions": questions,
        }

    def _response_suggestion(self, ctx: dict) -> dict:
        name = (ctx.get("contact_name") or "there").split()[0]
        articles = ctx.get("articles", [])[:2]
        steps = f" In the meantime, this guide may help: {articles[0]['title']}." if articles else ""
        return {
            "draft": (
                f'Hi {name},\n\nThank you for reporting "{ctx.get("title")}". We\'ve reviewed the details and '
                f"our team is working on it.{steps} We'll update you as soon as we have more information.\n\n"
                "Best regards"
            ),
            "tone": "reassuring",
            "cited_article_ids": [a["id"] for a in articles[:1]],
        }

    def _routing_explanation(self, ctx: dict) -> dict:
        candidates = ctx.get("candidates", [])
        return {
            "explanations": [
                {
                    "user_id": c["user_id"],
                    "explanation": (
                        f"[mock] {c['name']}: {c['open_tickets']} open ticket(s), "
                        f"{c['category_resolved']} resolved in this category recently."
                    ),
                }
                for c in candidates
            ],
            "reasoning": "[mock] Ranked by the deterministic scorer (workload and category experience).",
        }

    def _knowledge_answer(self, ctx: dict) -> dict:
        sources = ctx.get("sources", [])
        if not sources:
            return {
                "answer": "[mock] I couldn't find anything in the knowledge base or resolved tickets about this.",
                "steps": [],
                "source_ids": [],
                "confidence": 0.2,
            }
        top = sources[0]
        steps = []
        for line in re.split(r"\n+|(?<=\.)\s+", top.get("text", "")):
            line = re.sub(r"^\[mock\]\s*|^(?:problem|resolution|cause):\s*", "", line.strip(), flags=re.I)
            # Skip Markdown headings, emphasis-only notes and fragments.
            if len(line) > 8 and not line.startswith(("#", "_", "*")):
                steps.append(line)
        steps = steps[:4]
        return {
            "answer": f'[mock] The closest match is "{top["title"]}".',
            "steps": steps,
            "source_ids": [s["id"] for s in sources[:3]],
            "confidence": _conf(0.3 + 0.1 * len(sources)),
        }

    def _insights(self, ctx: dict) -> dict:
        insights = []
        for row in ctx.get("top_categories", [])[:2]:
            if row["count"] >= 3:
                insights.append(
                    {
                        "type": "recurring_issue",
                        "title": f"Recurring {row['name']} issues",
                        "body": f"[mock] {row['count']} {row['name']} tickets in the period.",
                        "evidence": [f"{row['count']} tickets"],
                    }
                )
        for row in ctx.get("repeat_assets", [])[:2]:
            insights.append(
                {
                    "type": "pattern",
                    "title": f"Asset {row['asset_tag']} keeps failing",
                    "body": f"[mock] {row['count']} tickets for {row['name']} at {row['customer']}.",
                    "evidence": [f"{row['count']} tickets"],
                }
            )
        if ctx.get("due_soon", 0) or ctx.get("overdue", 0):
            insights.append(
                {
                    "type": "sla_risk",
                    "title": "Tickets at risk of missing their deadline",
                    "body": f"[mock] {ctx.get('overdue', 0)} overdue and {ctx.get('due_soon', 0)} due within 24 hours.",
                    "evidence": [f"overdue={ctx.get('overdue', 0)}", f"due_soon={ctx.get('due_soon', 0)}"],
                }
            )
        return {
            "insights": insights
            or [
                {
                    "type": "pattern",
                    "title": "No notable patterns",
                    "body": "[mock] Nothing stood out in this period.",
                    "evidence": [],
                }
            ]
        }

    def _knowledge_extraction(self, ctx: dict) -> dict:
        words = Counter(w for w in _words(_text(ctx)) if len(w) > 4)
        return {
            "title": f"How to resolve: {ctx.get('title')}",
            "summary": f"[mock] {_first_sentences(ctx.get('resolution_notes') or ctx.get('description', ''), 1)}",
            "body": (
                f"## Problem\n{ctx.get('description', '')}\n\n## Resolution\n{ctx.get('resolution_notes', '')}\n\n"
                "_Draft generated by the demo AI provider. Review before publishing._"
            ),
            "tags": [w for w, _ in words.most_common(3)],
        }
