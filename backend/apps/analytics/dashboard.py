"""
Dashboard metrics. Read-only aggregation over other modules, always starting from
`visible_tickets` so every role sees figures for exactly the tickets it may see.

Metrics owned by modules that haven't shipped yet (SLA, field service) are
returned as `null` with an explanation in `unavailable` instead of a placeholder
number, so the UI can never present an invented figure.
"""

from datetime import timedelta
from zoneinfo import ZoneInfo

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.organizations.tenancy import TenantContext
from apps.tickets.models import ACTIVE_STATUSES, Priority, TicketHistory, TicketStatus
from apps.tickets.selectors import can_see_internal, visible_tickets

UNAVAILABLE = {
    "sla_compliance": "SLA policies arrive in Phase 6.",
}


def _hours(delta) -> float | None:
    return round(delta.total_seconds() / 3600, 1) if delta is not None else None


def summary(tenant: TenantContext, *, days: int = 30) -> dict:
    now = timezone.now()
    since = now - timedelta(days=days)
    qs = visible_tickets(tenant).filter(archived_at__isnull=True)
    active = Q(status__in=ACTIVE_STATUSES)

    counts = qs.aggregate(
        total=Count("id"),
        open=Count("id", filter=active),
        new=Count("id", filter=Q(status=TicketStatus.NEW)),
        in_progress=Count("id", filter=Q(status=TicketStatus.IN_PROGRESS)),
        resolved=Count("id", filter=Q(status=TicketStatus.RESOLVED)),
        closed=Count("id", filter=Q(status=TicketStatus.CLOSED)),
        overdue=Count("id", filter=active & Q(due_at__lt=now)),
        critical_open=Count("id", filter=active & Q(priority=Priority.CRITICAL)),
        unassigned_open=Count("id", filter=active & Q(assigned_agent__isnull=True)),
        created_in_period=Count("id", filter=Q(created_at__gte=since)),
        resolved_in_period=Count("id", filter=Q(resolved_at__gte=since)),
    )
    resolution = ExpressionWrapper(F("resolved_at") - F("created_at"), output_field=DurationField())
    first_response = ExpressionWrapper(F("first_response_at") - F("created_at"), output_field=DurationField())
    averages = qs.aggregate(
        avg_resolution=Avg(resolution, filter=Q(resolved_at__gte=since)),
        avg_first_response=Avg(first_response, filter=Q(first_response_at__isnull=False, created_at__gte=since)),
    )
    return {
        "period_days": days,
        **counts,
        "avg_resolution_hours": _hours(averages["avg_resolution"]),
        "avg_first_response_hours": _hours(averages["avg_first_response"]),
        "sla_compliance": None,
        **_field_service_figures(tenant),
        "unavailable": {**UNAVAILABLE, **_field_service_unavailable(tenant)},
        "generated_at": now,
    }


def trends(tenant: TenantContext, *, days: int = 30) -> list[dict]:
    """Daily created vs resolved counts, bucketed in the organization's timezone."""
    tz = ZoneInfo(tenant.organization.timezone or "UTC")
    today = timezone.now().astimezone(tz).date()
    start = today - timedelta(days=days - 1)
    qs = visible_tickets(tenant)
    created = dict(
        qs.filter(created_at__date__gte=start - timedelta(days=1))
        .annotate(day=TruncDate("created_at", tzinfo=tz))
        .values("day")
        .annotate(n=Count("id"))
        .values_list("day", "n")
    )
    resolved = dict(
        qs.filter(resolved_at__isnull=False, resolved_at__date__gte=start - timedelta(days=1))
        .annotate(day=TruncDate("resolved_at", tzinfo=tz))
        .values("day")
        .annotate(n=Count("id"))
        .values_list("day", "n")
    )
    return [
        {"date": d.isoformat(), "created": created.get(d, 0), "resolved": resolved.get(d, 0)}
        for d in (start + timedelta(days=i) for i in range(days))
    ]


def breakdown(tenant: TenantContext) -> dict:
    qs = visible_tickets(tenant).filter(archived_at__isnull=True)
    by_status = dict(qs.values("status").annotate(n=Count("id")).values_list("status", "n"))
    by_priority = dict(
        qs.filter(status__in=ACTIVE_STATUSES).values("priority").annotate(n=Count("id")).values_list("priority", "n")
    )
    by_category = list(
        qs.filter(status__in=ACTIVE_STATUSES).values("category__name").annotate(n=Count("id")).order_by("-n")[:8]
    )
    return {
        "status": [{"status": s.value, "label": s.label, "count": by_status.get(s.value, 0)} for s in TicketStatus],
        "priority": [{"priority": p.value, "label": p.label, "count": by_priority.get(p.value, 0)} for p in Priority],
        "category": [{"category": row["category__name"] or "Uncategorised", "count": row["n"]} for row in by_category],
    }


def agent_workload(tenant: TenantContext, *, days: int = 30) -> list[dict]:
    since = timezone.now() - timedelta(days=days)
    resolution = ExpressionWrapper(F("resolved_at") - F("created_at"), output_field=DurationField())
    rows = (
        visible_tickets(tenant)
        .filter(assigned_agent__isnull=False, archived_at__isnull=True)
        .values("assigned_agent", "assigned_agent__first_name", "assigned_agent__last_name", "assigned_agent__email")
        .annotate(
            open=Count("id", filter=Q(status__in=ACTIVE_STATUSES)),
            resolved=Count("id", filter=Q(resolved_at__gte=since)),
            avg_resolution=Avg(resolution, filter=Q(resolved_at__gte=since)),
        )
        .order_by("-open")[:10]
    )
    return [
        {
            "user_id": str(r["assigned_agent"]),
            "name": f"{r['assigned_agent__first_name']} {r['assigned_agent__last_name']}".strip()
            or r["assigned_agent__email"],
            "open": r["open"],
            "resolved": r["resolved"],
            "avg_resolution_hours": _hours(r["avg_resolution"]),
        }
        for r in rows
    ]


def recent_activity(tenant: TenantContext, *, limit: int = 15) -> list[dict]:
    qs = TicketHistory.objects.filter(ticket__in=visible_tickets(tenant)).select_related("ticket", "actor")
    if not can_see_internal(tenant):
        qs = qs.filter(internal=False)
    return [
        {
            "id": h.id,
            "event": h.event,
            "field": h.field,
            "old_value": h.old_value,
            "new_value": h.new_value,
            "actor": h.actor.full_name if h.actor else ("AI" if h.actor_type == "ai" else "System"),
            "ticket": {"id": str(h.ticket_id), "reference": h.ticket.reference, "title": h.ticket.title},
            "created_at": h.created_at,
        }
        for h in qs.order_by("-created_at", "-id")[:limit]
    ]


def _field_service_figures(tenant: TenantContext) -> dict:
    from apps.field_service.models import ACTIVE_WORK_ORDER_STATUSES
    from apps.field_service.selectors import active_technicians, available_now_count, visible_work_orders

    perms = tenant.permissions
    sees_team = "technicians.view" in perms and "work_orders.view_all" in perms
    sees_orders = bool({"work_orders.view_all", "work_orders.view_own"} & perms)
    active_orders = visible_work_orders(tenant).filter(status__in=ACTIVE_WORK_ORDER_STATUSES)
    return {
        "technicians_available": available_now_count(tenant.organization) if sees_team else None,
        "technicians_total": active_technicians(tenant.organization).count() if sees_team else None,
        "active_work_orders": active_orders.count() if sees_orders else None,
    }


def _field_service_unavailable(tenant: TenantContext) -> dict:
    perms = tenant.permissions
    out = {}
    if not ("technicians.view" in perms and "work_orders.view_all" in perms):
        out["technicians_available"] = "Visible to dispatchers."
    if not ({"work_orders.view_all", "work_orders.view_own"} & perms):
        out["active_work_orders"] = "Not available for your role."
    return out
