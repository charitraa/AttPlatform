"""
Deterministic assignee scoring. The LLM never picks the assignee; it only explains
this ranking, so routing keeps working when the AI provider is down or mocked.

Factors (each normalised to 0..1):
  * workload   - fewer open tickets is better (weight 0.5)
  * experience - tickets in this ticket's category resolved in the last 90 days (weight 0.4)
  * recency    - signed in during the last 7 days (weight 0.1)
Technician availability, skills and location arrive with field service (Phase 5)
and will join this score.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from apps.organizations.catalog import RoleCode
from apps.organizations.models import Membership
from apps.tickets.models import ACTIVE_STATUSES, Ticket
from apps.tickets.services import AGENT_ROLES, TECHNICIAN_ROLES

WEIGHTS = {"workload": 0.5, "experience": 0.4, "recency": 0.1}


@dataclass
class Candidate:
    user_id: str
    name: str
    role: str
    open_tickets: int
    category_resolved: int
    active_recently: bool
    score: float = 0.0
    factors: dict | None = None


# Front-line roles are routed to first; administrators only when nobody else is available.
PREFERRED_AGENT_ROLES = frozenset({RoleCode.SUPPORT_AGENT, RoleCode.OPS_MANAGER})


def _eligible(ticket: Ticket, roles) -> list[Membership]:
    return list(
        Membership.objects.filter(
            organization=ticket.organization, is_active=True, role__code__in=roles
        ).select_related("user", "role")
    )


def rank_candidates(ticket: Ticket, *, kind: str = "agent", limit: int = 5) -> list[Candidate]:
    field = "assigned_agent" if kind == "agent" else "assigned_technician"
    if kind == "agent":
        members = _eligible(ticket, PREFERRED_AGENT_ROLES) or _eligible(ticket, AGENT_ROLES)
    else:
        members = _eligible(ticket, TECHNICIAN_ROLES)
    if not members:
        return []
    user_ids = [m.user_id for m in members]
    since = timezone.now() - timedelta(days=90)
    stats = {
        row[field]: row
        for row in Ticket.objects.filter(organization=ticket.organization, **{f"{field}__in": user_ids})
        .values(field)
        .annotate(
            open=Count("id", filter=Q(status__in=ACTIVE_STATUSES, archived_at__isnull=True)),
            experience=Count("id", filter=Q(category_id=ticket.category_id, resolved_at__gte=since))
            if ticket.category_id
            else Count("id", filter=Q(pk__in=[])),
        )
    }
    week_ago = timezone.now() - timedelta(days=7)
    candidates = [
        Candidate(
            user_id=str(m.user_id),
            name=m.user.full_name,
            role=m.role.name,
            open_tickets=stats.get(m.user_id, {}).get("open", 0),
            category_resolved=stats.get(m.user_id, {}).get("experience", 0),
            active_recently=bool(m.user.last_login and m.user.last_login >= week_ago),
        )
        for m in members
    ]
    max_open = max(c.open_tickets for c in candidates) or 1
    max_exp = max(c.category_resolved for c in candidates) or 1
    for c in candidates:
        factors = {
            "workload": round(1 - c.open_tickets / max_open, 3) if max_open else 1.0,
            "experience": round(c.category_resolved / max_exp, 3),
            "recency": 1.0 if c.active_recently else 0.0,
        }
        c.factors = factors
        c.score = round(sum(WEIGHTS[k] * v for k, v in factors.items()), 3)
    candidates.sort(key=lambda c: (-c.score, c.open_tickets, c.name))
    return candidates[:limit]


def routing_confidence(candidates: list[Candidate]) -> float:
    """Clear winners get high confidence; near-ties stay low so they go to a human."""
    if not candidates:
        return 0.0
    if len(candidates) == 1:
        return 0.6
    gap = candidates[0].score - candidates[1].score
    return round(min(0.95, 0.5 + gap), 3)
