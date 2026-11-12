"""
Analytics reports: each is `columns` + `rows` so the same result renders as a
table in the app and as CSV. Dates are whole days in the organization's time zone
(`start` and `end` inclusive). Durations are hours with one decimal.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.db.models.functions import TruncDate

from apps.organizations.tenancy import TenantContext

MAX_DAYS = 366


@dataclass
class Column:
    key: str
    label: str
    kind: str = "number"  # text | number | hours | percent | date


@dataclass
class Report:
    name: str
    title: str
    description: str
    columns: list[Column]
    rows: list[dict]
    start: date
    end: date

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "columns": [c.__dict__ for c in self.columns],
            "rows": self.rows,
        }


@dataclass
class Window:
    start: date
    end: date
    tz: ZoneInfo

    @property
    def since(self) -> datetime:
        return datetime.combine(self.start, time(0), tzinfo=self.tz)

    @property
    def until(self) -> datetime:  # exclusive
        return datetime.combine(self.end + timedelta(days=1), time(0), tzinfo=self.tz)


def _hours(delta) -> float | None:
    return round(delta.total_seconds() / 3600, 1) if delta is not None else None


def _pct(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


_DUR = DurationField()


def _since(field_a: str, field_b: str):
    return ExpressionWrapper(F(field_a) - F(field_b), output_field=_DUR)


# ------------------------------------------------------------------ reports
def ticket_volume(tenant: TenantContext, w: Window) -> Report:
    from apps.tickets.selectors import visible_tickets

    qs = visible_tickets(tenant)
    created = dict(
        qs.filter(created_at__gte=w.since, created_at__lt=w.until)
        .annotate(d=TruncDate("created_at", tzinfo=w.tz))
        .values("d")
        .annotate(n=Count("id"))
        .values_list("d", "n")
    )
    resolved = {
        r["d"]: r
        for r in qs.filter(resolved_at__gte=w.since, resolved_at__lt=w.until)
        .annotate(d=TruncDate("resolved_at", tzinfo=w.tz))
        .values("d")
        .annotate(n=Count("id"), avg=Avg(_since("resolved_at", "created_at")))
    }
    responded = {
        r["d"]: r["avg"]
        for r in qs.filter(first_response_at__gte=w.since, first_response_at__lt=w.until)
        .annotate(d=TruncDate("first_response_at", tzinfo=w.tz))
        .values("d")
        .annotate(avg=Avg(_since("first_response_at", "created_at")))
    }
    rows, day = [], w.start
    while day <= w.end:
        r = resolved.get(day, {})
        rows.append(
            {
                "date": day.isoformat(),
                "created": created.get(day, 0),
                "resolved": r.get("n", 0),
                "avg_first_response_h": _hours(responded.get(day)),
                "avg_resolution_h": _hours(r.get("avg")),
            }
        )
        day += timedelta(days=1)
    return Report(
        "ticket_volume",
        "Ticket volume",
        "Tickets created and resolved per day, with average times.",
        [
            Column("date", "Date", "date"),
            Column("created", "Created"),
            Column("resolved", "Resolved"),
            Column("avg_first_response_h", "Avg first response (h)", "hours"),
            Column("avg_resolution_h", "Avg resolution (h)", "hours"),
        ],
        rows,
        w.start,
        w.end,
    )


def tickets_by_category(tenant: TenantContext, w: Window) -> Report:
    from apps.sla.models import MetricStatus
    from apps.tickets.models import ACTIVE_STATUSES
    from apps.tickets.selectors import visible_tickets

    qs = visible_tickets(tenant).filter(created_at__gte=w.since, created_at__lt=w.until)
    data = (
        qs.values("category__name")
        .annotate(
            created=Count("id"),
            open=Count("id", filter=Q(status__in=ACTIVE_STATUSES)),
            resolved=Count("id", filter=Q(resolved_at__isnull=False)),
            avg_res=Avg(_since("resolved_at", "created_at"), filter=Q(resolved_at__isnull=False)),
            sla_met=Count("id", filter=Q(sla__resolution_status=MetricStatus.MET)),
            sla_breached=Count("id", filter=Q(sla__resolution_status=MetricStatus.BREACHED)),
        )
        .order_by("-created")
    )
    rows = [
        {
            "category": r["category__name"] or "Uncategorised",
            "created": r["created"],
            "open": r["open"],
            "resolved": r["resolved"],
            "avg_resolution_h": _hours(r["avg_res"]),
            "sla_compliance": _pct(r["sla_met"], r["sla_met"] + r["sla_breached"]),
        }
        for r in data
    ]
    return Report(
        "tickets_by_category",
        "Tickets by category",
        "Tickets opened in the period, grouped by category.",
        [
            Column("category", "Category", "text"),
            Column("created", "Opened"),
            Column("open", "Still open"),
            Column("resolved", "Resolved"),
            Column("avg_resolution_h", "Avg resolution (h)", "hours"),
            Column("sla_compliance", "SLA met", "percent"),
        ],
        rows,
        w.start,
        w.end,
    )


def agent_performance(tenant: TenantContext, w: Window) -> Report:
    from apps.sla.models import MetricStatus
    from apps.tickets.models import TicketHistory
    from apps.tickets.selectors import visible_tickets

    qs = visible_tickets(tenant).filter(created_at__gte=w.since, created_at__lt=w.until, assigned_agent__isnull=False)
    data = (
        qs.values("assigned_agent_id", "assigned_agent__first_name", "assigned_agent__last_name")
        .annotate(
            assigned=Count("id"),
            resolved=Count("id", filter=Q(resolved_at__isnull=False)),
            avg_first=Avg(_since("first_response_at", "created_at"), filter=Q(first_response_at__isnull=False)),
            avg_res=Avg(_since("resolved_at", "created_at"), filter=Q(resolved_at__isnull=False)),
            breaches=Count(
                "id",
                filter=Q(sla__resolution_status=MetricStatus.BREACHED) | Q(sla__response_status=MetricStatus.BREACHED),
            ),
        )
        .order_by("-resolved", "-assigned")
    )
    reopened = dict(
        TicketHistory.objects.filter(ticket__in=qs, field="status", new_value="reopened")
        .values("ticket__assigned_agent_id")
        .annotate(n=Count("id"))
        .values_list("ticket__assigned_agent_id", "n")
    )
    rows = [
        {
            "agent": f"{r['assigned_agent__first_name']} {r['assigned_agent__last_name']}".strip(),
            "assigned": r["assigned"],
            "resolved": r["resolved"],
            "avg_first_response_h": _hours(r["avg_first"]),
            "avg_resolution_h": _hours(r["avg_res"]),
            "sla_breaches": r["breaches"],
            "reopened": reopened.get(r["assigned_agent_id"], 0),
        }
        for r in data
    ]
    return Report(
        "agent_performance",
        "Agent performance",
        "Tickets opened in the period, by assigned agent.",
        [
            Column("agent", "Agent", "text"),
            Column("assigned", "Assigned"),
            Column("resolved", "Resolved"),
            Column("avg_first_response_h", "Avg first response (h)", "hours"),
            Column("avg_resolution_h", "Avg resolution (h)", "hours"),
            Column("sla_breaches", "SLA breaches"),
            Column("reopened", "Reopened"),
        ],
        rows,
        w.start,
        w.end,
    )


def sla_compliance(tenant: TenantContext, w: Window) -> Report:
    from apps.sla.services import compliance

    data = compliance(tenant.organization, start=w.since, end=w.until)
    rows = [
        {
            "priority": p.title(),
            "tickets": r["tickets"],
            "response_met": r["response_met"],
            "response_breached": r["response_breached"],
            "response_compliance": r["response_compliance"],
            "resolution_met": r["resolution_met"],
            "resolution_breached": r["resolution_breached"],
            "resolution_compliance": r["resolution_compliance"],
        }
        for p, r in reversed(list(data["by_priority"].items()))
    ]
    return Report(
        "sla_compliance",
        "SLA compliance",
        "Targets met and breached for tickets opened in the period.",
        [
            Column("priority", "Priority", "text"),
            Column("tickets", "Tickets"),
            Column("response_met", "Response met"),
            Column("response_breached", "Response breached"),
            Column("response_compliance", "Response %", "percent"),
            Column("resolution_met", "Resolution met"),
            Column("resolution_breached", "Resolution breached"),
            Column("resolution_compliance", "Resolution %", "percent"),
        ],
        rows,
        w.start,
        w.end,
    )


def field_service(tenant: TenantContext, w: Window) -> Report:
    from apps.field_service.models import WorkOrder, WorkOrderStatus

    qs = WorkOrder.objects.filter(
        organization=tenant.organization, created_at__gte=w.since, created_at__lt=w.until, technician__isnull=False
    )
    data = (
        qs.values("technician__user__first_name", "technician__user__last_name")
        .annotate(
            assigned=Count("id"),
            completed=Count("id", filter=Q(status=WorkOrderStatus.COMPLETED)),
            cancelled=Count("id", filter=Q(status=WorkOrderStatus.CANCELLED)),
            avg_on_site=Avg(
                _since("actual_end", "actual_start"), filter=Q(actual_end__isnull=False, actual_start__isnull=False)
            ),
            confirmed=Count("id", filter=Q(customer_confirmed_at__isnull=False)),
            avg_rating=Avg("customer_rating"),
        )
        .order_by("-completed")
    )
    rows = [
        {
            "technician": f"{r['technician__user__first_name']} {r['technician__user__last_name']}".strip(),
            "assigned": r["assigned"],
            "completed": r["completed"],
            "cancelled": r["cancelled"],
            "avg_on_site_h": _hours(r["avg_on_site"]),
            "signed_off": _pct(r["confirmed"], r["completed"]),
            "avg_rating": round(r["avg_rating"], 2) if r["avg_rating"] is not None else None,
        }
        for r in data
    ]
    return Report(
        "field_service",
        "Field service",
        "Work orders created in the period, by technician.",
        [
            Column("technician", "Technician", "text"),
            Column("assigned", "Assigned"),
            Column("completed", "Completed"),
            Column("cancelled", "Cancelled"),
            Column("avg_on_site_h", "Avg time on site (h)", "hours"),
            Column("signed_off", "Customer signed off", "percent"),
            Column("avg_rating", "Avg rating"),
        ],
        rows,
        w.start,
        w.end,
    )


def customer_satisfaction(tenant: TenantContext, w: Window) -> Report:
    from apps.portal.models import CustomerFeedback

    data = (
        CustomerFeedback.objects.filter(
            organization=tenant.organization, created_at__gte=w.since, created_at__lt=w.until
        )
        .values("customer__name")
        .annotate(
            responses=Count("id"),
            avg=Avg("rating"),
            low=Count("id", filter=Q(rating__lte=2)),
            high=Count("id", filter=Q(rating__gte=4)),
        )
        .order_by("customer__name")
    )
    rows = [
        {
            "customer": r["customer__name"],
            "responses": r["responses"],
            "avg_rating": round(r["avg"], 2),
            "satisfied": _pct(r["high"], r["responses"]),
            "unhappy": r["low"],
        }
        for r in data
    ]
    return Report(
        "customer_satisfaction",
        "Customer satisfaction",
        "Ratings customers gave in the portal (tickets and visits), by customer.",
        [
            Column("customer", "Customer", "text"),
            Column("responses", "Responses"),
            Column("avg_rating", "Avg rating (1–5)"),
            Column("satisfied", "Rated 4–5", "percent"),
            Column("unhappy", "Rated 1–2"),
        ],
        rows,
        w.start,
        w.end,
    )


def ai_accuracy(tenant: TenantContext, w: Window) -> Report:
    from apps.ai.models import AIRecommendation

    S = AIRecommendation.Status
    data = (
        AIRecommendation.objects.filter(
            organization=tenant.organization, created_at__gte=w.since, created_at__lt=w.until
        )
        .values("type", "analysis__prompt_version", "analysis__is_mock")
        .annotate(
            total=Count("id"),
            accepted=Count("id", filter=Q(status=S.ACCEPTED)),
            auto=Count("id", filter=Q(status=S.AUTO_APPLIED)),
            overridden=Count("id", filter=Q(status=S.OVERRIDDEN)),
            rejected=Count("id", filter=Q(status=S.REJECTED)),
        )
        .order_by("type", "analysis__prompt_version")
    )
    rows = [
        {
            "suggestion": r["type"].replace("_", " "),
            "prompt_version": r["analysis__prompt_version"],
            "source": "Demo (mock)" if r["analysis__is_mock"] else "Model",
            "total": r["total"],
            "accepted": r["accepted"],
            "auto_applied": r["auto"],
            "overridden": r["overridden"],
            "rejected": r["rejected"],
            "acceptance_rate": _pct(r["accepted"], r["accepted"] + r["overridden"] + r["rejected"]),
        }
        for r in data
    ]
    return Report(
        "ai_accuracy",
        "AI accuracy",
        "How often people accepted AI suggestions, per prompt version.",
        [
            Column("suggestion", "Suggestion", "text"),
            Column("prompt_version", "Prompt version", "text"),
            Column("source", "Source", "text"),
            Column("total", "Total"),
            Column("accepted", "Accepted"),
            Column("auto_applied", "Auto-applied"),
            Column("overridden", "Overridden"),
            Column("rejected", "Dismissed"),
            Column("acceptance_rate", "Acceptance", "percent"),
        ],
        rows,
        w.start,
        w.end,
    )


REPORTS: dict[str, Callable[[TenantContext, Window], Report]] = {
    "ticket_volume": ticket_volume,
    "tickets_by_category": tickets_by_category,
    "agent_performance": agent_performance,
    "sla_compliance": sla_compliance,
    "field_service": field_service,
    "customer_satisfaction": customer_satisfaction,
    "ai_accuracy": ai_accuracy,
}


# ---------------------------------------------------------------------- CSV
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value) -> str:
    """Spreadsheet-safe cell: text that a spreadsheet would run as a formula gets a leading quote."""
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def to_csv(report: Report) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([c.label for c in report.columns])
    for row in report.rows:
        writer.writerow([_cell(row.get(c.key)) for c in report.columns])
    return "﻿" + buf.getvalue()  # BOM so Excel reads UTF-8 (customer names, °C …)
