"""
AI capabilities and the human-in-the-loop decision flow.

Flow: request_* creates a pending AIAnalysis and enqueues `tasks.run_analysis`
(after commit). The task calls `execute(analysis)`, which builds a minimal
context, runs the capability through `client.run`, and post-processes the output
into recommendations, insights or draft articles.

Policies (Organization.settings):
  * ai_enabled (default true): master switch for automatic triggers.
  * ai_auto_triage (default false): auto-apply category/priority when confident and
    nobody has set them by hand.
  * routing_policy: manual | recommend (default) | auto. "auto" assigns the top
    candidate when routing confidence clears AI_AUTO_APPLY_MIN_CONFIDENCE.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import exceptions

from apps.audit import services as audit
from apps.core.exceptions import DomainError
from apps.knowledge.models import KnowledgeArticle
from apps.organizations.tenancy import TenantContext
from apps.tickets import services as ticket_services
from apps.tickets.models import ACTIVE_STATUSES, Ticket, TicketAssignment, TicketCategory, TicketComment

from . import client, retrieval, routing
from .models import AIAnalysis, AIInsight, AIRecommendation, Capability

logger = logging.getLogger(__name__)
TRIAGE_KINDS = (Capability.CLASSIFICATION, Capability.PRIORITY, Capability.ROUTING)
REUSE_WINDOW = timedelta(minutes=10)


# --------------------------------------------------------------------- policies
def org_setting(organization, key: str, default):
    return (organization.settings or {}).get(key, default)


def ai_enabled(organization) -> bool:
    return bool(org_setting(organization, "ai_enabled", True))


def threshold() -> float:
    return settings.AI_AUTO_APPLY_MIN_CONFIDENCE


# ---------------------------------------------------------------------- context
def _comments(ticket: Ticket, *, include_internal: bool) -> list[dict]:
    qs = ticket.comments.select_related("author").order_by("created_at")
    if not include_internal:
        qs = qs.filter(visibility=TicketComment.Visibility.PUBLIC)
    return [
        {
            "author_is_staff": c.source != TicketComment.Source.CUSTOMER,
            "visibility": c.visibility,
            "body": c.body[:2000],
            "at": c.created_at.isoformat(),
        }
        for c in qs[:40]
    ]


def ticket_context(ticket: Ticket, capability: str) -> dict:
    """Only what each capability needs. Customer-facing drafts never see internal notes."""
    base = {"title": ticket.title, "description": ticket.description[:6000]}
    if capability in (Capability.CLASSIFICATION, Capability.PRIORITY):
        base |= {
            "channel": ticket.channel,
            "customer_tier": ticket.customer.tier,
            "asset_name": ticket.asset.name if ticket.asset_id else None,
        }
        if capability == Capability.CLASSIFICATION:
            base["categories"] = [
                {"id": str(c.id), "name": str(c), "department": c.department, "description": c.description}
                for c in TicketCategory.objects.filter(organization=ticket.organization, is_active=True).select_related(
                    "parent"
                )
            ]
    elif capability == Capability.SUMMARY:
        base |= {
            "status": ticket.status,
            "priority": ticket.priority,
            "comments": _comments(ticket, include_internal=True),
        }
    elif capability == Capability.RESPONSE_SUGGESTION:
        base |= {
            "status": ticket.status,
            "contact_name": ticket.contact.name if ticket.contact_id else "",
            "comments": _comments(ticket, include_internal=False),
            "articles": [
                {"id": s["object_id"], "title": s["title"], "text": s["text"][:1200]}
                for s in retrieval.search(
                    ticket.organization, f"{ticket.title} {ticket.description}", limit=3, exclude_ticket_id=ticket.id
                )
                if s["kind"] == "article"
            ],
        }
    elif capability == Capability.KNOWLEDGE_EXTRACTION:
        base |= {
            "category": str(ticket.category) if ticket.category_id else None,
            "resolution_notes": ticket.resolution_notes[:4000],
            "troubleshooting": [c["body"] for c in _comments(ticket, include_internal=True)][:15],
        }
    return base


# --------------------------------------------------------------------- requests
def _create(organization, kind, *, ticket=None, user=None, trigger="manual", params=None) -> AIAnalysis:
    return AIAnalysis.objects.create(
        organization=organization, ticket=ticket, kind=kind, requested_by=user, trigger=trigger, input=params or {}
    )


def _enqueue(analyses: list[AIAnalysis]) -> None:
    from .tasks import run_analysis

    for a in analyses:
        transaction.on_commit(lambda a_id=str(a.id): run_analysis.delay(a_id))


@transaction.atomic
def request_ticket_analysis(*, ticket: Ticket, kinds, user=None, trigger="manual") -> list[AIAnalysis]:
    analyses = [_create(ticket.organization, k, ticket=ticket, user=user, trigger=trigger) for k in kinds]
    _enqueue(analyses)
    return analyses


@transaction.atomic
def request_answer(*, organization, question: str, user) -> AIAnalysis:
    question = question.strip()
    if len(question) < 3:
        raise exceptions.ValidationError({"question": ["Ask a question of at least a few words."]})
    analysis = _create(organization, Capability.KNOWLEDGE_ANSWER, user=user, params={"question": question[:1000]})
    _enqueue([analysis])
    return analysis


@transaction.atomic
def request_insights(*, organization, user=None, days: int = 30, trigger="manual") -> AIAnalysis:
    analysis = _create(organization, Capability.INSIGHTS, user=user, trigger=trigger, params={"days": days})
    _enqueue([analysis])
    return analysis


# -------------------------------------------------------------------- execution
def execute(analysis: AIAnalysis) -> AIAnalysis:
    """Run one analysis end to end. Idempotent: completed/failed analyses are left alone."""
    if analysis.status in (AIAnalysis.Status.COMPLETED, AIAnalysis.Status.FAILED):
        return analysis
    handler = {
        Capability.CLASSIFICATION: _run_classification,
        Capability.PRIORITY: _run_priority,
        Capability.ROUTING: _run_routing,
        Capability.SUMMARY: _run_simple,
        Capability.RESPONSE_SUGGESTION: _run_simple,
        Capability.KNOWLEDGE_ANSWER: _run_answer,
        Capability.INSIGHTS: _run_insights,
        Capability.KNOWLEDGE_EXTRACTION: _run_extraction,
    }[analysis.kind]
    return handler(analysis)


def _reuse_recent(analysis: AIAnalysis, context: dict) -> bool:
    """Identical input analysed moments ago (e.g. a double click): reuse it instead of paying twice."""
    analysis.input_hash = client.input_hash(analysis.kind, context)
    recent = (
        AIAnalysis.objects.filter(
            kind=analysis.kind,
            ticket=analysis.ticket,
            organization=analysis.organization,
            input_hash=analysis.input_hash,
            status=AIAnalysis.Status.COMPLETED,
            completed_at__gte=timezone.now() - REUSE_WINDOW,
        )
        .exclude(pk=analysis.pk)
        .first()
    )
    if recent is None:
        analysis.save(update_fields=["input_hash", "updated_at"])
        return False
    for f in ("output", "confidence", "reasoning", "provider", "model", "prompt_version", "is_mock"):
        setattr(analysis, f, getattr(recent, f))
    analysis.status, analysis.completed_at, analysis.latency_ms = AIAnalysis.Status.COMPLETED, timezone.now(), 0
    analysis.save()
    return True


def _run_simple(analysis: AIAnalysis) -> AIAnalysis:
    context = ticket_context(analysis.ticket, analysis.kind)
    if _reuse_recent(analysis, context):
        return analysis
    return client.run(analysis, analysis.kind, context)


def _supersede(ticket: Ticket, rec_type: str) -> None:
    AIRecommendation.objects.filter(ticket=ticket, type=rec_type, status=AIRecommendation.Status.PENDING).update(
        status=AIRecommendation.Status.SUPERSEDED, updated_at=timezone.now()
    )


def _recommend(analysis: AIAnalysis, rec_type: str, value: dict, previous: dict | None) -> AIRecommendation:
    _supersede(analysis.ticket, rec_type)
    return AIRecommendation.objects.create(
        organization=analysis.organization,
        analysis=analysis,
        ticket=analysis.ticket,
        type=rec_type,
        value=value,
        previous_value=previous,
        confidence=analysis.confidence,
        reasoning=analysis.reasoning,
    )


def _confident(analysis: AIAnalysis) -> bool:
    return analysis.confidence is not None and float(analysis.confidence) >= threshold()


def _auto_apply(rec: AIRecommendation, field: str, value) -> None:
    try:
        ticket_services.apply_field_change(
            ticket=rec.ticket, field=field, value=value, reason=f"AI {rec.type} (confidence {rec.confidence})"
        )
    except DomainError:
        return
    rec.status = AIRecommendation.Status.AUTO_APPLIED
    rec.decided_at = timezone.now()
    rec.save(update_fields=["status", "decided_at", "updated_at"])


def _run_classification(analysis: AIAnalysis) -> AIAnalysis:
    ticket = analysis.ticket
    context = ticket_context(ticket, Capability.CLASSIFICATION)
    if not _reuse_recent(analysis, context):
        client.run(analysis, Capability.CLASSIFICATION, context)
    if analysis.status != AIAnalysis.Status.COMPLETED:
        return analysis
    category_id = analysis.output.get("category_id")
    category = (
        TicketCategory.objects.filter(organization=ticket.organization, pk=category_id, is_active=True).first()
        if category_id
        else None
    )
    if category is None or category.id == ticket.category_id:
        return analysis
    rec = _recommend(
        analysis,
        AIRecommendation.Type.CATEGORY,
        {"category_id": str(category.id), "name": str(category)},
        {"category_id": str(ticket.category_id), "name": str(ticket.category)} if ticket.category_id else None,
    )
    if (
        org_setting(ticket.organization, "ai_auto_triage", False)
        and ticket.category_id is None
        and _confident(analysis)
    ):
        _auto_apply(rec, "category", category)
    return analysis


def _run_priority(analysis: AIAnalysis) -> AIAnalysis:
    ticket = analysis.ticket
    context = ticket_context(ticket, Capability.PRIORITY)
    if not _reuse_recent(analysis, context):
        client.run(analysis, Capability.PRIORITY, context)
    if analysis.status != AIAnalysis.Status.COMPLETED:
        return analysis
    priority = analysis.output["priority"]
    if priority == ticket.priority:
        return analysis
    rec = _recommend(analysis, AIRecommendation.Type.PRIORITY, {"priority": priority}, {"priority": ticket.priority})
    # Never override a priority a person chose.
    if (
        org_setting(ticket.organization, "ai_auto_triage", False)
        and ticket.priority_source != Ticket.PrioritySource.MANUAL
        and _confident(analysis)
    ):
        _auto_apply(rec, "priority", priority)
    return analysis


def _run_routing(analysis: AIAnalysis) -> AIAnalysis:
    ticket = analysis.ticket
    agents = routing.rank_candidates(ticket, kind="agent")
    # Suggest a technician when on-site work is likely: an asset is involved or a work order exists.
    needs_field = bool(ticket.asset_id) or ticket.work_orders.exists()
    technicians = routing.rank_candidates(ticket, kind="technician") if needs_field else []
    candidates_ctx = [
        {
            "user_id": c.user_id,
            "name": c.name,
            "role": c.role,
            "open_tickets": c.open_tickets,
            "category_resolved": c.category_resolved,
            "score": c.score,
            "factors": c.factors,
        }
        for c in agents + technicians
    ]
    explanations = {}
    explanation_error = ""
    if candidates_ctx:
        context = {
            "title": ticket.title,
            "category": str(ticket.category) if ticket.category_id else None,
            "candidates": candidates_ctx,
        }
        client.run(analysis, "routing_explanation", context)
        if analysis.status == AIAnalysis.Status.COMPLETED:
            explanations = {e["user_id"]: e["explanation"] for e in analysis.output.get("explanations", [])}
        else:
            explanation_error = analysis.error  # ranking still stands without the explanations

    def describe(c):
        return (
            explanations.get(c.user_id)
            or c.summary
            or (
                f"{c.open_tickets} open ticket(s); {c.category_resolved} resolved in this category in the last 90 days."
            )
        )

    confidence = routing.routing_confidence(agents)
    analysis.output = {
        "agents": [
            {
                "user_id": c.user_id,
                "name": c.name,
                "role": c.role,
                "score": c.score,
                "factors": c.factors,
                "explanation": describe(c),
            }
            for c in agents
        ],
        "technicians": [
            {"user_id": c.user_id, "name": c.name, "score": c.score, "factors": c.factors, "explanation": describe(c)}
            for c in technicians
        ],
        "weights": routing.WEIGHTS,
    }
    analysis.status = AIAnalysis.Status.COMPLETED
    analysis.confidence = Decimal(str(confidence))
    analysis.reasoning = "Ranked by workload, category experience and recent activity." + (
        " Explanations unavailable: " + explanation_error if explanation_error else ""
    )
    analysis.error = ""
    analysis.completed_at = timezone.now()
    analysis.save()

    if agents and agents[0].user_id != str(ticket.assigned_agent_id or ""):
        top = agents[0]
        rec = _recommend(
            analysis,
            AIRecommendation.Type.ASSIGNEE,
            {"user_id": top.user_id, "name": top.name},
            {"user_id": str(ticket.assigned_agent_id), "name": ticket.assigned_agent.full_name}
            if ticket.assigned_agent_id
            else None,
        )
        if (
            org_setting(ticket.organization, "routing_policy", "recommend") == "auto"
            and ticket.assigned_agent_id is None
            and confidence >= threshold()
        ):
            try:
                ticket_services.assign(
                    organization=ticket.organization,
                    actor=None,
                    ticket=ticket,
                    agent_id=top.user_id,
                    source=TicketAssignment.Source.AI_AUTO,
                )
                rec.status, rec.decided_at = AIRecommendation.Status.AUTO_APPLIED, timezone.now()
                rec.save(update_fields=["status", "decided_at", "updated_at"])
            except (DomainError, exceptions.ValidationError) as exc:
                logger.info("AI auto-assignment skipped for %s: %s", ticket.id, exc)
    if technicians and technicians[0].user_id != str(ticket.assigned_technician_id or ""):
        top = technicians[0]
        _recommend(
            analysis,
            AIRecommendation.Type.TECHNICIAN,
            {"user_id": top.user_id, "name": top.name},
            {"user_id": str(ticket.assigned_technician_id), "name": ticket.assigned_technician.full_name}
            if ticket.assigned_technician_id
            else None,
        )
    return analysis


def _run_answer(analysis: AIAnalysis) -> AIAnalysis:
    question = analysis.input.get("question", "")
    sources = retrieval.search(analysis.organization, question, limit=5)
    context = {
        "question": question,
        "sources": [{"id": s["id"], "title": s["title"], "text": s["text"]} for s in sources],
    }
    client.run(analysis, Capability.KNOWLEDGE_ANSWER, context)
    if analysis.status == AIAnalysis.Status.COMPLETED:
        cited = set(analysis.output.get("source_ids", []))
        # Attach source metadata so the UI can link to them; drop ids the model invented.
        analysis.output["sources"] = [
            {"id": s["id"], "kind": s["kind"], "object_id": s["object_id"], "title": s["title"]}
            for s in sources
            if s["id"] in cited or not cited
        ]
        analysis.output["source_ids"] = [
            i for i in analysis.output.get("source_ids", []) if i in {s["id"] for s in sources}
        ]
        analysis.save(update_fields=["output", "updated_at"])
    return analysis


def insight_statistics(organization, days: int) -> dict:
    now = timezone.now()
    since = now - timedelta(days=days)
    qs = Ticket.objects.filter(organization=organization, archived_at__isnull=True)
    recent = qs.filter(created_at__gte=since)
    return {
        "period_days": days,
        "created": recent.count(),
        "resolved": qs.filter(resolved_at__gte=since).count(),
        "open": qs.filter(status__in=ACTIVE_STATUSES).count(),
        "overdue": qs.filter(status__in=ACTIVE_STATUSES, due_at__lt=now).count(),
        "due_soon": qs.filter(
            status__in=ACTIVE_STATUSES, due_at__gte=now, due_at__lt=now + timedelta(hours=24)
        ).count(),
        "reopened": recent.filter(history__event="status_changed", history__new_value="reopened").distinct().count(),
        "top_categories": [
            {"name": r["category__name"] or "Uncategorised", "count": r["n"]}
            for r in recent.values("category__name").annotate(n=Count("id")).order_by("-n")[:5]
        ],
        "top_customers": [
            {"name": r["customer__name"], "count": r["n"]}
            for r in recent.values("customer__name").annotate(n=Count("id")).order_by("-n")[:5]
        ],
        "repeat_assets": [
            {
                "asset_tag": r["asset__asset_tag"],
                "name": r["asset__name"],
                "customer": r["customer__name"],
                "count": r["n"],
            }
            for r in recent.filter(asset__isnull=False)
            .values("asset__asset_tag", "asset__name", "customer__name")
            .annotate(n=Count("id"))
            .filter(n__gte=2)
            .order_by("-n")[:5]
        ],
        "critical_open": qs.filter(status__in=ACTIVE_STATUSES, priority="critical").count(),
        "unassigned_open": qs.filter(status__in=ACTIVE_STATUSES, assigned_agent__isnull=True).count(),
    }


def _run_insights(analysis: AIAnalysis) -> AIAnalysis:
    days = int(analysis.input.get("days", 30))
    stats = insight_statistics(analysis.organization, days)  # aggregates only: no customer text leaves
    client.run(analysis, Capability.INSIGHTS, stats)
    if analysis.status == AIAnalysis.Status.COMPLETED:
        end = timezone.now()
        AIInsight.objects.bulk_create(
            [
                AIInsight(
                    organization=analysis.organization,
                    analysis=analysis,
                    type=i["type"],
                    title=i["title"][:200],
                    body=i["body"],
                    evidence=i.get("evidence", []),
                    period_start=end - timedelta(days=days),
                    period_end=end,
                )
                for i in analysis.output.get("insights", [])[:5]
            ]
        )
    return analysis


def _run_extraction(analysis: AIAnalysis) -> AIAnalysis:
    ticket = analysis.ticket
    context = ticket_context(ticket, Capability.KNOWLEDGE_EXTRACTION)
    client.run(analysis, Capability.KNOWLEDGE_EXTRACTION, context)
    if analysis.status == AIAnalysis.Status.COMPLETED:
        out = analysis.output
        KnowledgeArticle.objects.create(
            organization=ticket.organization,
            title=out["title"][:200],
            summary=out["summary"][:500],
            body=out["body"],
            category=ticket.category,
            tags=[t.lower()[:40] for t in out.get("tags", [])][:10],
            status=KnowledgeArticle.Status.DRAFT,
            source=KnowledgeArticle.Source.AI_EXTRACTED,
            source_ticket=ticket,
            source_analysis=analysis,
        )
    return analysis


# -------------------------------------------------------------------- decisions
def _pending(rec: AIRecommendation) -> AIRecommendation:
    rec = AIRecommendation.objects.select_for_update().select_related("ticket", "analysis").get(pk=rec.pk)
    if rec.status != AIRecommendation.Status.PENDING:
        raise DomainError("This recommendation has already been decided.")
    return rec


def _apply_value(rec: AIRecommendation, value: dict, *, tenant: TenantContext, request, accepted: bool):
    """Apply a value through the normal ticket services so history, audit and events stay consistent."""
    ticket, user = rec.ticket, tenant.membership.user
    if rec.type == AIRecommendation.Type.CATEGORY:
        category = TicketCategory.objects.filter(
            organization=ticket.organization, pk=value.get("category_id"), is_active=True
        ).first()
        if category is None:
            raise exceptions.ValidationError({"value": ["Unknown category."]})
        if accepted:
            ticket_services.apply_field_change(
                ticket=ticket,
                field="category",
                value=category,
                actor=user,
                request=request,
                reason="AI recommendation accepted",
            )
        else:
            ticket_services.update_ticket(tenant=tenant, ticket=ticket, data={"category": category}, request=request)
    elif rec.type == AIRecommendation.Type.PRIORITY:
        priority = value.get("priority")
        if priority not in {"low", "medium", "high", "critical"}:
            raise exceptions.ValidationError({"value": ["Unknown priority."]})
        if accepted:
            ticket_services.apply_field_change(
                ticket=ticket,
                field="priority",
                value=priority,
                actor=user,
                request=request,
                reason="AI recommendation accepted",
            )
        else:
            ticket_services.update_ticket(tenant=tenant, ticket=ticket, data={"priority": priority}, request=request)
    else:
        field = "agent_id" if rec.type == AIRecommendation.Type.ASSIGNEE else "technician_id"
        source = TicketAssignment.Source.AI_ACCEPTED if accepted else TicketAssignment.Source.MANUAL
        ticket_services.assign(
            organization=ticket.organization,
            actor=user,
            ticket=ticket,
            **{field: value.get("user_id")},
            source=source,
            request=request,
        )


@transaction.atomic
def decide(
    *,
    rec: AIRecommendation,
    tenant: TenantContext,
    decision: str,
    value: dict | None = None,
    note: str = "",
    request=None,
) -> AIRecommendation:
    rec = _pending(rec)
    if decision == "accept":
        _apply_value(rec, rec.value, tenant=tenant, request=request, accepted=True)
        rec.status = AIRecommendation.Status.ACCEPTED
    elif decision == "override":
        if not value:
            raise exceptions.ValidationError({"value": ["Provide the value to use instead."]})
        _apply_value(rec, value, tenant=tenant, request=request, accepted=False)
        rec.status, rec.override_value = AIRecommendation.Status.OVERRIDDEN, value
    elif decision == "reject":
        rec.status = AIRecommendation.Status.REJECTED
    else:
        raise exceptions.ValidationError({"decision": ["Use accept, reject or override."]})
    rec.decided_by, rec.decided_at, rec.note = tenant.membership.user, timezone.now(), note[:500]
    rec.save()
    audit.record(
        f"ai.recommendation_{rec.status}",
        request=request,
        target=rec,
        changes={"type": rec.type, "value": rec.value, "override": rec.override_value, "ticket": rec.ticket.reference},
    )
    return rec


def acceptance_stats(organization, days: int = 90) -> list[dict]:
    """Per capability and prompt version: how often people accepted the AI's suggestion."""
    since = timezone.now() - timedelta(days=days)
    S = AIRecommendation.Status
    rows = (
        AIRecommendation.objects.filter(organization=organization, created_at__gte=since)
        .values("type", "analysis__prompt_version", "analysis__is_mock")
        .annotate(
            total=Count("id"),
            accepted=Count("id", filter=Q(status=S.ACCEPTED)),
            auto_applied=Count("id", filter=Q(status=S.AUTO_APPLIED)),
            overridden=Count("id", filter=Q(status=S.OVERRIDDEN)),
            rejected=Count("id", filter=Q(status=S.REJECTED)),
            pending=Count("id", filter=Q(status=S.PENDING)),
        )
        .order_by("type", "analysis__prompt_version")
    )
    out = []
    for r in rows:
        decided = r["accepted"] + r["overridden"] + r["rejected"]
        out.append(
            {
                "type": r["type"],
                "prompt_version": r["analysis__prompt_version"],
                "is_mock": r["analysis__is_mock"],
                "total": r["total"],
                "accepted": r["accepted"],
                "auto_applied": r["auto_applied"],
                "overridden": r["overridden"],
                "rejected": r["rejected"],
                "pending": r["pending"],
                "acceptance_rate": round(r["accepted"] / decided, 3) if decided else None,
            }
        )
    return out
