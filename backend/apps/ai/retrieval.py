"""
Retrieval for the knowledge assistant: PostgreSQL full-text search over published
articles and resolved tickets (both have GIN expression indexes). The interface
is small on purpose so pgvector-based semantic search can replace it later.
"""

from __future__ import annotations

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector

from apps.knowledge.models import KnowledgeArticle
from apps.tickets.models import Ticket, TicketStatus

TICKET_VECTOR = SearchVector("title", "description", config="english")
ARTICLE_VECTOR = SearchVector("title", "summary", "body", config="english")


def _query(text: str) -> SearchQuery:
    # websearch syntax, OR-ing terms so natural questions still match.
    terms = [t for t in text.replace('"', " ").split() if len(t) > 2]
    return SearchQuery(" OR ".join(terms) or text, search_type="websearch", config="english")


def search(organization, text: str, *, limit: int = 5, exclude_ticket_id=None) -> list[dict]:
    query = _query(text)
    articles = (
        KnowledgeArticle.objects.filter(organization=organization, status=KnowledgeArticle.Status.PUBLISHED)
        .annotate(rank=SearchRank(ARTICLE_VECTOR, query))
        .filter(rank__gt=0.01)
        .order_by("-rank")[:limit]
    )
    tickets = (
        Ticket.objects.filter(organization=organization, status__in=[TicketStatus.RESOLVED, TicketStatus.CLOSED])
        .exclude(resolution_notes="")
        .exclude(pk=exclude_ticket_id)
        .annotate(rank=SearchRank(TICKET_VECTOR, query))
        .filter(rank__gt=0.01)
        .order_by("-rank")[:limit]
    )
    results = [
        {
            "id": f"article:{a.id}",
            "kind": "article",
            "object_id": str(a.id),
            "title": a.title,
            "text": (a.summary + "\n" + a.body)[:2000],
            "rank": float(a.rank),
        }
        for a in articles
    ] + [
        {
            "id": f"ticket:{t.id}",
            "kind": "ticket",
            "object_id": str(t.id),
            "title": f"{t.reference} {t.title}",
            "text": f"Problem: {t.description[:800]}\nResolution: {t.resolution_notes[:1200]}",
            "rank": float(t.rank),
        }
        for t in tickets
    ]
    # Published articles are curated, so they win ties against raw tickets.
    results.sort(key=lambda r: -(r["rank"] * (1.25 if r["kind"] == "article" else 1.0)))
    return results[:limit]
