"""Read-side queries for field service, including deterministic technician scoring."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from django.db.models import Count, QuerySet
from django.utils import timezone

from apps.organizations.catalog import RoleCode
from apps.organizations.tenancy import TenantContext

from .models import (
    ACTIVE_WORK_ORDER_STATUSES,
    Appointment,
    Skill,
    Technician,
    TechnicianAvailability,
    WorkOrder,
)

WEIGHTS = {"skills": 0.35, "availability": 0.25, "workload": 0.2, "distance": 0.2}
DISTANCE_CAP_KM = 50.0


def active_technicians(organization) -> QuerySet[Technician]:
    return (
        Technician.objects.filter(
            organization=organization,
            user__memberships__organization=organization,
            user__memberships__is_active=True,
            user__memberships__role__code=RoleCode.FIELD_TECHNICIAN,
        )
        .select_related("user")
        .distinct()
    )


def visible_work_orders(tenant: TenantContext) -> QuerySet[WorkOrder]:
    qs = WorkOrder.objects.filter(organization=tenant.organization)
    if "work_orders.view_all" in tenant.permissions:
        return qs
    if "work_orders.view_own" in tenant.permissions:
        return qs.filter(technician__user=tenant.membership.user)
    return qs.none()


def on_time_off(technician: Technician, at) -> bool:
    return TechnicianAvailability.objects.filter(
        technician=technician, type=TechnicianAvailability.Type.TIME_OFF, starts_at__lte=at, ends_at__gt=at
    ).exists()


def available_now_count(organization) -> int:
    now = timezone.now()
    off = TechnicianAvailability.objects.filter(
        type=TechnicianAvailability.Type.TIME_OFF, starts_at__lte=now, ends_at__gt=now
    ).values("technician_id")
    return active_technicians(organization).filter(status=Technician.Status.AVAILABLE).exclude(id__in=off).count()


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    lat1, lng1, lat2, lng2 = map(lambda v: math.radians(float(v)), (lat1, lng1, lat2, lng2))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


@dataclass
class TechnicianScore:
    technician_id: str
    user_id: str
    name: str
    status: str
    active_jobs: int
    distance_km: float | None
    matched_skills: list[str]
    missing_skills: list[str]
    score: float = 0.0
    factors: dict = field(default_factory=dict)
    blocked_reason: str = ""


def rank_technicians(
    organization, *, category_id=None, lat=None, lng=None, when=None, limit: int = 5, include_blocked: bool = False
) -> list[TechnicianScore]:
    """
    Score every active technician for a job. Hard blocks (on leave, off duty, time
    off at `when`) are ranked last with a reason instead of hidden, so dispatchers
    can still see why someone wasn't suggested.
    """
    when = when or timezone.now()
    techs = list(active_technicians(organization).prefetch_related("skills__skill"))
    if not techs:
        return []
    required = (
        list(Skill.objects.filter(organization=organization, ticket_categories__id=category_id)) if category_id else []
    )
    load = dict(
        WorkOrder.objects.filter(technician__in=techs, status__in=ACTIVE_WORK_ORDER_STATUSES)
        .values("technician")
        .annotate(n=Count("id"))
        .values_list("technician", "n")
    )
    day_jobs = dict(
        Appointment.objects.filter(
            technician__in=techs, status=Appointment.Status.CONFIRMED, starts_at__date=when.date()
        )
        .values("technician")
        .annotate(n=Count("id"))
        .values_list("technician", "n")
    )
    time_off = set(
        TechnicianAvailability.objects.filter(
            technician__in=techs, type=TechnicianAvailability.Type.TIME_OFF, starts_at__lte=when, ends_at__gt=when
        ).values_list("technician_id", flat=True)
    )
    max_load = max(load.values(), default=0) or 1
    results = []
    for t in techs:
        levels = {ts.skill_id: ts.level for ts in t.skills.all()}
        if required:
            skills_score = sum(levels.get(s.id, 0) / 5 for s in required) / len(required)
        else:
            skills_score = 0.5  # no requirement: neutral
        blocked = ""
        if t.status == Technician.Status.ON_LEAVE:
            blocked = "On leave"
        elif t.status == Technician.Status.OFF_DUTY:
            blocked = "Off duty"
        elif t.id in time_off:
            blocked = "Time off"
        if blocked:
            availability = 0.0
        elif day_jobs.get(t.id, 0) >= t.max_daily_jobs:
            availability = 0.2
        else:
            availability = 1.0 if t.status == Technician.Status.AVAILABLE else 0.5
        distance = None
        if lat is not None and lng is not None and t.home_lat is not None and t.home_lng is not None:
            distance = round(haversine_km(lat, lng, t.home_lat, t.home_lng), 1)
        distance_score = 0.5 if distance is None else max(0.0, 1 - min(distance, DISTANCE_CAP_KM) / DISTANCE_CAP_KM)
        factors = {
            "skills": round(skills_score, 3),
            "availability": availability,
            "workload": round(1 - load.get(t.id, 0) / max_load, 3),
            "distance": round(distance_score, 3),
        }
        score = sum(WEIGHTS[k] * v for k, v in factors.items())
        results.append(
            TechnicianScore(
                technician_id=str(t.id),
                user_id=str(t.user_id),
                name=t.user.full_name,
                status=t.status,
                active_jobs=load.get(t.id, 0),
                distance_km=distance,
                matched_skills=[s.name for s in required if s.id in levels],
                missing_skills=[s.name for s in required if s.id not in levels],
                score=round(0.0 if blocked else score, 3),
                factors=factors,
                blocked_reason=blocked,
            )
        )
    results.sort(key=lambda r: (bool(r.blocked_reason), -r.score, r.active_jobs, r.name))
    if not include_blocked:
        results = [r for r in results if not r.blocked_reason]
    return results[:limit]


def schedule_window(organization, start, end, technician_ids=None):
    appts = (
        Appointment.objects.filter(organization=organization, starts_at__lt=end, ends_at__gt=start)
        .exclude(status=Appointment.Status.CANCELLED)
        .select_related("work_order__customer", "technician__user")
    )
    blocks = TechnicianAvailability.objects.filter(
        technician__organization=organization, starts_at__lt=end, ends_at__gt=start
    ).select_related("technician__user")
    if technician_ids:
        appts = appts.filter(technician_id__in=technician_ids)
        blocks = blocks.filter(technician_id__in=technician_ids)
    return appts, blocks
