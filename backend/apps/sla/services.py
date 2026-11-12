"""
SLA business logic.

`sync_ticket` is the single entry point used by the ticket event subscribers: it
reconciles a ticket's SLA clock with the ticket's *current* state (status, priority,
first response) instead of reacting to individual events, so every path that
changes a ticket (staff transitions, customer replies, auto-assignment, AI
priority changes) keeps the clock right, and running it twice is harmless.

`scan` is the monitor (Celery beat, every minute). Warnings and breaches are
recorded once per metric (database constraint) and published as domain events
(`sla.warning`, `sla.breached`, `sla.escalated`) for notifications and real-time.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.core import events
from apps.tickets.models import Priority, Ticket, TicketStatus

from .business_time import Calendar, add_business_seconds, business_seconds_between
from .models import BusinessHours, MetricStatus, SLAEvent, SLAInstance, SLAPolicy, SLATarget

logger = logging.getLogger(__name__)

PAUSING_STATUSES = frozenset({TicketStatus.PENDING_CUSTOMER, TicketStatus.PENDING_PARTS})
STOPPED_STATUSES = frozenset({TicketStatus.RESOLVED, TicketStatus.CLOSED})
OPEN_METRIC = (MetricStatus.ON_TRACK, MetricStatus.WARNING)

# Defaults for a new organization: (first response, resolution) in working minutes.
DEFAULT_TARGETS = {
    Priority.CRITICAL: (30, 4 * 60),
    Priority.HIGH: (60, 8 * 60),
    Priority.MEDIUM: (4 * 60, 3 * 8 * 60),
    Priority.LOW: (8 * 60, 5 * 8 * 60),
}
DEFAULT_SCHEDULE = {d: [["09:00", "17:00"]] for d in ("sun", "mon", "tue", "wed", "thu", "fri")}


# --------------------------------------------------------------------- calendars
def calendar_for(hours: BusinessHours | None) -> Calendar:
    if hours is None:
        return Calendar.always()
    return Calendar.from_schedule(
        timezone=hours.timezone,
        schedule=hours.schedule,
        holidays=hours.holidays.values_list("date", flat=True),
    )


@transaction.atomic
def ensure_default_policy(organization) -> SLAPolicy:
    """Every organization starts with working hours and a default policy it can edit."""
    existing = SLAPolicy.objects.filter(organization=organization, is_default=True).first()
    if existing:
        return existing
    hours, _ = BusinessHours.objects.get_or_create(
        organization=organization,
        name="Standard hours",
        defaults={"timezone": organization.timezone or "UTC", "schedule": DEFAULT_SCHEDULE},
    )
    policy = SLAPolicy.objects.create(
        organization=organization,
        name="Standard",
        description="Default targets for every ticket that no other policy matches.",
        is_default=True,
        business_hours=hours,
        priority_order=1000,
    )
    SLATarget.objects.bulk_create(
        SLATarget(policy=policy, priority=p, first_response_minutes=r, resolution_minutes=s)
        for p, (r, s) in DEFAULT_TARGETS.items()
    )
    return policy


# ---------------------------------------------------------------------- matching
def _matches(policy: SLAPolicy, ticket: Ticket) -> bool:
    c = policy.conditions or {}
    checks = (
        ("categories", str(ticket.category_id) if ticket.category_id else None),
        ("customer_tiers", ticket.customer.tier if ticket.customer_id else None),
        ("channels", ticket.channel),
    )
    return all(not c.get(key) or value in {str(v) for v in c[key]} for key, value in checks)


def select_policy(ticket: Ticket) -> tuple[SLAPolicy, SLATarget] | None:
    """First active policy (by `priority_order`) whose conditions match and that has a target for the priority."""
    policies = (
        SLAPolicy.objects.filter(organization_id=ticket.organization_id, is_active=True)
        .select_related("business_hours")
        .prefetch_related("targets")
        .order_by("is_default", "priority_order", "name")  # the default policy is the fallback
    )
    for policy in policies:
        if policy.is_default or _matches(policy, ticket):
            target = next((t for t in policy.targets.all() if t.priority == ticket.priority), None)
            if target:
                return policy, target
    return None


# --------------------------------------------------------------------- the clock
def _event(sla: SLAInstance, type_: str, metric: str = "", actor=None, **payload) -> bool:
    """Record an SLA event; returns False if this once-only event already exists."""
    try:
        with transaction.atomic():
            SLAEvent.objects.create(sla=sla, type=type_, metric=metric, actor=actor, payload=payload)
        return True
    except IntegrityError:
        return False


def _compute(sla: SLAInstance, cal: Calendar) -> None:
    resp, res = sla.response_minutes * 60, sla.resolution_minutes * 60
    pct = sla.warning_threshold_pct / 100
    sla.response_due_at = add_business_seconds(cal, sla.started_at, resp)
    sla.response_warn_at = add_business_seconds(cal, sla.started_at, resp * pct)
    sla.resolution_due_at = add_business_seconds(cal, sla.started_at, res + sla.paused_seconds)
    sla.resolution_warn_at = add_business_seconds(cal, sla.started_at, res * pct + sla.paused_seconds)


def _mirror_due_at(sla: SLAInstance) -> None:
    """Ticket.due_at is the running resolution deadline (none while paused or stopped)."""
    due = None if sla.is_paused or sla.resolution_status == MetricStatus.MET else sla.resolution_due_at
    Ticket.objects.filter(pk=sla.ticket_id).exclude(due_at=due).update(due_at=due)


def _apply(ticket: Ticket, now: datetime) -> SLAInstance | None:
    match = select_policy(ticket)
    if match is None:
        return None
    policy, target = match
    sla = SLAInstance(
        organization_id=ticket.organization_id,
        ticket=ticket,
        policy=policy,
        policy_name=policy.name,
        business_hours=policy.business_hours,
        priority=ticket.priority,
        response_minutes=target.first_response_minutes,
        resolution_minutes=target.resolution_minutes,
        warning_threshold_pct=target.warning_threshold_pct,
        started_at=ticket.created_at or now,
    )
    _compute(sla, calendar_for(policy.business_hours))
    sla.save()
    _event(sla, SLAEvent.Type.APPLIED, policy=policy.name, priority=ticket.priority)
    return sla


def _retarget(sla: SLAInstance, ticket: Ticket, cal: Calendar) -> None:
    """Priority changed: take the policy's target for the new priority; open metrics are re-evaluated."""
    target = (
        SLATarget.objects.filter(policy_id=sla.policy_id, priority=ticket.priority).first() if sla.policy_id else None
    )
    if target is None:  # policy deleted or no target for that priority: keep the old numbers
        sla.priority = ticket.priority
        return
    old = {"priority": sla.priority, "response": sla.response_minutes, "resolution": sla.resolution_minutes}
    sla.priority = ticket.priority
    sla.response_minutes, sla.resolution_minutes = target.first_response_minutes, target.resolution_minutes
    sla.warning_threshold_pct = target.warning_threshold_pct
    _compute(sla, cal)
    # A breach is final; a warning is re-evaluated by the monitor against the new deadline.
    if sla.response_status == MetricStatus.WARNING:
        sla.response_status = MetricStatus.ON_TRACK
    if sla.resolution_status == MetricStatus.WARNING:
        sla.resolution_status = MetricStatus.ON_TRACK
    _event(sla, SLAEvent.Type.RECALCULATED, previous=old, priority=sla.priority)


@transaction.atomic
def sync_ticket(ticket_id, *, now: datetime | None = None) -> SLAInstance | None:
    """Reconcile the SLA clock with the ticket's current state. Idempotent."""
    now = now or timezone.now()
    ticket = Ticket.objects.select_related("customer").filter(pk=ticket_id).first()
    if ticket is None:
        return None
    sla = SLAInstance.objects.select_for_update().filter(ticket=ticket).first()
    if sla is None:
        if ticket.archived_at or ticket.status in STOPPED_STATUSES:
            return None
        sla = _apply(ticket, now)
        if sla is None:
            return None
    cal = calendar_for(sla.business_hours)

    if ticket.priority != sla.priority:
        _retarget(sla, ticket, cal)

    # First response: the first public staff reply, or the resolution if nobody replied.
    responded = ticket.first_response_at or (now if ticket.status in STOPPED_STATUSES else None)
    if sla.responded_at is None and responded:
        sla.responded_at = responded
        if sla.response_status in OPEN_METRIC:
            sla.response_status = MetricStatus.MET
            _event(sla, SLAEvent.Type.MET, SLAEvent.Metric.RESPONSE, at=responded.isoformat())

    should_pause = ticket.status in PAUSING_STATUSES | STOPPED_STATUSES
    if should_pause and not sla.is_paused:
        sla.paused_at = now
        _event(sla, SLAEvent.Type.PAUSED, SLAEvent.Metric.RESOLUTION, status=ticket.status)
    elif not should_pause and sla.is_paused:
        sla.paused_seconds += max(0, int(business_seconds_between(cal, sla.paused_at, now)))
        sla.paused_at = None
        _compute(sla, cal)
        _event(sla, SLAEvent.Type.RESUMED, SLAEvent.Metric.RESOLUTION, status=ticket.status)

    if ticket.status in STOPPED_STATUSES and sla.resolved_at is None:
        sla.resolved_at = ticket.resolved_at or now
        if sla.resolution_status in OPEN_METRIC:
            sla.resolution_status = MetricStatus.MET
            _event(sla, SLAEvent.Type.MET, SLAEvent.Metric.RESOLUTION, at=sla.resolved_at.isoformat())
    elif ticket.status not in STOPPED_STATUSES and sla.resolved_at is not None:  # reopened
        sla.resolved_at = None
        if sla.resolution_status == MetricStatus.MET:
            sla.resolution_status = MetricStatus.ON_TRACK

    sla.save()
    _mirror_due_at(sla)
    return sla


# ----------------------------------------------------------------------- monitor
def _publish(name: str, sla: SLAInstance, metric: str) -> None:
    events.publish(
        name,
        organization_id=str(sla.organization_id),
        ticket_id=str(sla.ticket_id),
        sla_id=str(sla.id),
        metric=metric,
        due_at=(sla.response_due_at if metric == SLAEvent.Metric.RESPONSE else sla.resolution_due_at).isoformat(),
    )


def _monitor_sets(now: datetime):
    R, S = SLAEvent.Metric.RESPONSE, SLAEvent.Metric.RESOLUTION
    running = Q(paused_at__isnull=True)
    return (
        (R, MetricStatus.BREACHED, Q(response_status__in=OPEN_METRIC, response_due_at__lte=now)),
        (
            R,
            MetricStatus.WARNING,
            Q(response_status=MetricStatus.ON_TRACK, response_warn_at__lte=now, response_due_at__gt=now),
        ),
        (S, MetricStatus.BREACHED, running & Q(resolution_status__in=OPEN_METRIC, resolution_due_at__lte=now)),
        (
            S,
            MetricStatus.WARNING,
            running
            & Q(resolution_status=MetricStatus.ON_TRACK, resolution_warn_at__lte=now, resolution_due_at__gt=now),
        ),
    )


def scan(*, now: datetime | None = None, batch: int = 500) -> dict[str, int]:
    """Mark warnings and breaches that are due. Safe to run concurrently (row locks, skip_locked)."""
    now = now or timezone.now()
    counts = {"warning": 0, "breached": 0, "escalated": 0}
    for metric, new_status, condition in _monitor_sets(now):
        ids = list(SLAInstance.objects.filter(condition).values_list("id", flat=True)[:batch])
        for sla_id in ids:
            with transaction.atomic():
                sla = (
                    SLAInstance.objects.select_for_update(skip_locked=True, of=("self",))
                    .filter(condition, pk=sla_id)
                    .select_related("policy", "ticket")
                    .first()
                )
                if sla is None:  # handled by another worker, or the ticket moved on
                    continue
                setattr(sla, f"{metric}_status", new_status)
                sla.save(update_fields=[f"{metric}_status", "updated_at"])
                if _event(sla, new_status, metric):
                    counts[new_status] += 1
                    _publish(f"sla.{new_status}", sla, metric)
                if new_status == MetricStatus.BREACHED and metric == SLAEvent.Metric.RESOLUTION:
                    counts["escalated"] += _escalate(sla)
    return counts


def _escalate(sla: SLAInstance) -> int:
    from apps.tickets import services as ticket_services

    if sla.escalated_at or not (sla.policy and sla.policy.escalate_on_breach):
        return 0
    ticket = ticket_services.escalate_for_sla(ticket=sla.ticket, reason="Resolution SLA breached")
    if ticket is None:
        return 0
    sla.escalated_at = timezone.now()
    sla.save(update_fields=["escalated_at", "updated_at"])
    if _event(sla, SLAEvent.Type.ESCALATED, SLAEvent.Metric.RESOLUTION):
        _publish("sla.escalated", sla, SLAEvent.Metric.RESOLUTION)
    return 1


# ----------------------------------------------------------------------- reports
def compliance(organization, *, start: datetime, end: datetime) -> dict:
    """Met vs breached per priority for SLAs whose resolution clock finished or breached in [start, end)."""
    qs = SLAInstance.objects.filter(organization=organization, started_at__gte=start, started_at__lt=end)
    rows = {}
    for p in Priority.values:
        sub = qs.filter(priority=p)
        decided = sub.filter(resolution_status__in=[MetricStatus.MET, MetricStatus.BREACHED])
        met = decided.filter(resolution_status=MetricStatus.MET).count()
        breached = decided.count() - met
        resp = sub.filter(response_status__in=[MetricStatus.MET, MetricStatus.BREACHED])
        resp_met = resp.filter(response_status=MetricStatus.MET).count()
        rows[p] = {
            "tickets": sub.count(),
            "resolution_met": met,
            "resolution_breached": breached,
            "resolution_compliance": round(met / (met + breached), 4) if met + breached else None,
            "response_met": resp_met,
            "response_breached": resp.count() - resp_met,
            "response_compliance": round(resp_met / resp.count(), 4) if resp.count() else None,
            "at_risk": sub.filter(resolution_status=MetricStatus.WARNING).count(),
        }
    total_met = sum(r["resolution_met"] for r in rows.values())
    total_decided = total_met + sum(r["resolution_breached"] for r in rows.values())
    return {
        "start": start,
        "end": end,
        "by_priority": rows,
        "resolution_compliance": round(total_met / total_decided, 4) if total_decided else None,
    }


def compliance_rate(organization, days: int = 30) -> float | None:
    now = timezone.now()
    return compliance(organization, start=now - timedelta(days=days), end=now)["resolution_compliance"]
