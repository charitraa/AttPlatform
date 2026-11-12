"""
Field-service business logic: work orders, assignment, the on-site workflow,
evidence, completion, customer confirmation, appointments and location pings.

Every mutation is transactional, audited and publishes a domain event
(`work_order.*`) for notifications (Phase 6).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import exceptions

from apps.audit import services as audit
from apps.core import events
from apps.core.exceptions import Conflict, DomainError, InvalidTransition
from apps.core.uploads import ALL_ALLOWED, IMAGES, validate_upload
from apps.organizations.catalog import RoleCode
from apps.organizations.models import Membership
from apps.organizations.services import next_sequence_value
from apps.organizations.tenancy import TenantContext
from apps.tickets import services as ticket_services
from apps.tickets.models import Ticket, TicketComment

from .lifecycle import CANCELLABLE_FROM, TECHNICIAN_DECLINE_FROM, TECHNICIAN_STEPS
from .models import (
    FIELD_ACTIVE_STATUSES,
    Appointment,
    Technician,
    TechnicianAvailability,
    TechnicianLocation,
    WorkOrder,
    WorkOrderEvidence,
    WorkOrderStatus,
    WorkOrderStatusLog,
)

LOCATION_RETENTION_DAYS = 30


def _publish(name: str, wo: WorkOrder, **extra) -> None:
    events.publish(name, organization_id=str(wo.organization_id), work_order_id=str(wo.id), **extra)


def _log(wo: WorkOrder, actor, old: str, new: str, note: str = "", lat=None, lng=None) -> None:
    WorkOrderStatusLog.objects.create(
        work_order=wo, from_status=old, to_status=new, actor=actor, note=note[:1000], lat=lat, lng=lng
    )


def technician_for(user, organization) -> Technician | None:
    return Technician.objects.filter(organization=organization, user=user).first()


def _release_technician(tech: Technician) -> None:
    """Busy → available once no other job keeps them in the field. Off duty / on leave are left alone."""
    if tech.status != Technician.Status.BUSY:
        return
    if not WorkOrder.objects.filter(technician=tech, status__in=FIELD_ACTIVE_STATUSES).exists():
        Technician.objects.filter(pk=tech.pk).update(status=Technician.Status.AVAILABLE, updated_at=timezone.now())
        tech.status = Technician.Status.AVAILABLE


def _release_visit(wo: WorkOrder) -> None:
    """Cancel the confirmed visit and clear the planned window (the job needs a new time)."""
    Appointment.objects.filter(work_order=wo, status=Appointment.Status.CONFIRMED).update(
        status=Appointment.Status.CANCELLED, updated_at=timezone.now()
    )
    wo.scheduled_start = wo.scheduled_end = None


def _carry_visit(wo: WorkOrder, technician: Technician | None) -> list[str]:
    """
    On reassignment the booked visit follows the job: it moves to the new technician when they
    are free at that time, otherwise it is released and the dispatcher picks a new slot.
    """
    appt = Appointment.objects.filter(work_order=wo, status=Appointment.Status.CONFIRMED).first()
    if appt is None:
        return []
    if technician is None:
        _release_visit(wo)
        return []
    try:
        warnings = _check_slot(technician, appt.starts_at, appt.ends_at, exclude_id=appt.pk)
        with transaction.atomic():
            Appointment.objects.filter(pk=appt.pk).update(technician=technician, updated_at=timezone.now())
        return warnings
    except (Conflict, exceptions.ValidationError, IntegrityError) as exc:
        reason = exc.detail if isinstance(exc, (Conflict, exceptions.ValidationError)) else "the slot is taken"
        if isinstance(reason, dict):
            reason = " ".join(str(m) for msgs in reason.values() for m in msgs)
        _release_visit(wo)
        when = timezone.localtime(appt.starts_at)
        return [f"The visit on {when:%d %b %H:%M} was released: {reason} Schedule a new time."]


# ------------------------------------------------------------------ technicians
@transaction.atomic
def ensure_technician_profile(membership: Membership) -> Technician:
    """Every active Field Technician gets a profile (created lazily)."""
    tech, _ = Technician.objects.get_or_create(organization=membership.organization, user=membership.user)
    return tech


# ------------------------------------------------------------------ work orders
@transaction.atomic
def create_work_order(*, tenant: TenantContext, data: dict, request=None) -> WorkOrder:
    org, user = tenant.organization, tenant.membership.user
    ticket: Ticket | None = data.get("ticket")
    customer = data.get("customer") or (ticket.customer if ticket else None)
    if customer is None:
        raise exceptions.ValidationError({"customer": ["Choose a customer or a ticket."]})
    if ticket and ticket.customer_id != customer.id:
        raise exceptions.ValidationError({"ticket": ["The ticket belongs to a different customer."]})
    asset = data.get("asset") or (ticket.asset if ticket else None)
    if asset and asset.customer_id != customer.id:
        raise exceptions.ValidationError({"asset": ["This asset does not belong to the customer."]})
    address = data.get("service_address") or ", ".join(filter(None, [customer.address_line1, customer.city]))

    wo = WorkOrder.objects.create(
        organization=org,
        number=next_sequence_value(org, "work_order"),
        ticket=ticket,
        customer=customer,
        asset=asset,
        title=(data.get("title") or (ticket.title if ticket else "")).strip()[:200],
        description=data.get("description") or (ticket.description if ticket else ""),
        priority=data.get("priority") or (ticket.priority if ticket else "medium"),
        service_address=address,
        lat=data.get("lat"),
        lng=data.get("lng"),
        scheduled_start=data.get("scheduled_start"),
        scheduled_end=data.get("scheduled_end"),
        created_by=user,
    )
    if not wo.title:
        raise exceptions.ValidationError({"title": ["Give the work order a title."]})
    _log(wo, user, "", WorkOrderStatus.CREATED)
    if ticket:
        ticket_services.add_comment(
            tenant=tenant,
            ticket=ticket,
            visibility=TicketComment.Visibility.INTERNAL,
            request=request,
            body=f"Work order {wo.reference} created for on-site service.",
            _skip_status_side_effects=True,
        )
    audit.record("work_order.created", request=request, target=wo, changes={"reference": wo.reference})
    _publish("work_order.created", wo)
    if data.get("technician"):
        wo = assign_technician(tenant=tenant, work_order=wo, technician=data["technician"], request=request)
    return wo


def _lock(wo: WorkOrder) -> WorkOrder:
    # Lock only the work order row: PostgreSQL cannot lock the nullable side of the joins.
    return WorkOrder.objects.select_for_update(of=("self",)).select_related("technician__user", "ticket").get(pk=wo.pk)


@transaction.atomic
def assign_technician(
    *,
    tenant: TenantContext,
    work_order: WorkOrder,
    technician: Technician | None,
    request=None,
    warnings: list[str] | None = None,
) -> WorkOrder:
    """Assign, reassign or unassign. Scheduling advisories are appended to `warnings` if given."""
    wo = _lock(work_order)
    if wo.status in (WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED):
        raise DomainError("Completed or cancelled work orders cannot be reassigned.")
    if wo.status in FIELD_ACTIVE_STATUSES:
        raise DomainError("The technician is already on the way or on site. Cancel the job to reassign it.")
    if technician is not None:
        active = Membership.objects.filter(
            organization=wo.organization, user=technician.user, is_active=True, role__code=RoleCode.FIELD_TECHNICIAN
        ).exists()
        if technician.organization_id != wo.organization_id or not active:
            raise exceptions.ValidationError({"technician": ["Choose an active technician from this organization."]})
    old_tech, old_status = wo.technician, wo.status
    visit_notes = _carry_visit(wo, technician) if old_tech != technician else []
    if warnings is not None:
        warnings.extend(visit_notes)
    wo.technician = technician
    wo.status = WorkOrderStatus.ASSIGNED if technician else WorkOrderStatus.CREATED
    wo.save(update_fields=["technician", "status", "scheduled_start", "scheduled_end", "updated_at"])
    actor = tenant.membership.user
    _log(wo, actor, old_status, wo.status, note=f"Assigned to {technician}" if technician else "Unassigned")
    # Keep the ticket's technician in step with its active work order.
    if wo.ticket_id and wo.ticket.status != "closed" and not wo.ticket.archived_at:
        ticket_services.assign(
            organization=wo.organization,
            actor=actor,
            ticket=wo.ticket,
            technician_id=technician.user_id if technician else None,
            request=request,
        )
    audit.record(
        "work_order.assigned",
        request=request,
        target=wo,
        changes={
            "technician": {"from": str(old_tech) if old_tech else None, "to": str(technician) if technician else None}
        },
    )
    _publish("work_order.assigned", wo, technician_user_id=str(technician.user_id) if technician else None)
    return wo


def _require_assigned_technician(tenant: TenantContext, wo: WorkOrder) -> Technician:
    tech = wo.technician
    if tech is None or tech.user_id != tenant.membership.user.id:
        raise exceptions.PermissionDenied("Only the assigned technician can update this job.")
    return tech


@transaction.atomic
def advance(
    *,
    tenant: TenantContext,
    work_order: WorkOrder,
    to_status: str,
    note: str = "",
    lat=None,
    lng=None,
    completion: dict | None = None,
    request=None,
) -> WorkOrder:
    """Technician field steps: accept → en route → on site → in progress → completed."""
    wo = _lock(work_order)
    tech = _require_assigned_technician(tenant, wo)
    if to_status not in TECHNICIAN_STEPS or wo.status not in TECHNICIAN_STEPS[to_status]:
        raise InvalidTransition(f"Cannot move a work order from '{wo.status}' to '{to_status}'.")
    now = timezone.now()
    if to_status == WorkOrderStatus.IN_PROGRESS:
        wo.actual_start = wo.actual_start or now
    if to_status == WorkOrderStatus.COMPLETED:
        _apply_completion(wo, completion or {})
        wo.actual_end = now
        if wo.actual_start and not wo.labor_minutes:
            wo.labor_minutes = max(1, int((now - wo.actual_start).total_seconds() // 60))
        if wo.labor_minutes and tech.hourly_cost is not None and wo.labor_cost is None:
            wo.labor_cost = (tech.hourly_cost * Decimal(wo.labor_minutes) / 60).quantize(Decimal("0.01"))
            wo.currency = wo.currency or tech.currency
        Appointment.objects.filter(work_order=wo, status=Appointment.Status.CONFIRMED).update(
            status=Appointment.Status.COMPLETED, updated_at=now
        )
    old = wo.status
    wo.status = to_status
    wo.save()
    # Technician status follows the job: busy while in the field, available once nothing keeps them there.
    if to_status in FIELD_ACTIVE_STATUSES and tech.status != Technician.Status.BUSY:
        tech.status = Technician.Status.BUSY
        tech.save(update_fields=["status", "updated_at"])
    elif to_status == WorkOrderStatus.COMPLETED:
        _release_technician(tech)
    _log(wo, tenant.membership.user, old, to_status, note=note, lat=lat, lng=lng)
    if to_status == WorkOrderStatus.COMPLETED and wo.ticket_id:
        ticket_services.add_comment(
            tenant=tenant,
            ticket=wo.ticket,
            visibility=TicketComment.Visibility.INTERNAL,
            request=request,
            body=f"Work order {wo.reference} completed by {tech}.\n\n{wo.completion_summary}",
            _skip_status_side_effects=True,
        )
    audit.record(
        "work_order.status_changed", request=request, target=wo, changes={"status": {"from": old, "to": to_status}}
    )
    _publish("work_order.status_changed", wo, old_status=old, new_status=to_status)
    return wo


def _apply_completion(wo: WorkOrder, data: dict) -> None:
    summary = (data.get("completion_summary") or wo.completion_summary).strip()
    if not summary:
        raise exceptions.ValidationError({"completion_summary": ["Describe the work carried out."]})
    if not wo.evidence.exists():
        raise exceptions.ValidationError({"evidence": ["Upload at least one photo or document before completing."]})
    wo.completion_summary = summary
    if "service_notes" in data:
        wo.service_notes = data["service_notes"]
    if "parts_used" in data:
        wo.parts_used = data["parts_used"]
        total = sum(
            (Decimal(str(p.get("unit_cost") or 0)) * int(p.get("quantity") or 1) for p in data["parts_used"]),
            Decimal("0"),
        )
        wo.parts_cost = total.quantize(Decimal("0.01")) if data["parts_used"] else None
    if data.get("labor_minutes"):
        wo.labor_minutes = data["labor_minutes"]


@transaction.atomic
def decline(*, tenant: TenantContext, work_order: WorkOrder, reason: str, request=None) -> WorkOrder:
    wo = _lock(work_order)
    _require_assigned_technician(tenant, wo)
    if wo.status not in TECHNICIAN_DECLINE_FROM:
        raise InvalidTransition("Jobs can only be handed back before travelling to site.")
    if not reason.strip():
        raise exceptions.ValidationError({"reason": ["Tell the dispatcher why you can't take this job."]})
    old, tech = wo.status, wo.technician
    wo.technician, wo.status = None, WorkOrderStatus.CREATED
    _release_visit(wo)
    wo.save(update_fields=["technician", "status", "scheduled_start", "scheduled_end", "updated_at"])
    _log(wo, tenant.membership.user, old, WorkOrderStatus.CREATED, note=f"Declined by {tech}: {reason.strip()}")
    audit.record("work_order.declined", request=request, target=wo, changes={"reason": reason.strip()[:300]})
    _publish("work_order.declined", wo, technician_user_id=str(tech.user_id))
    return wo


@transaction.atomic
def cancel(*, tenant: TenantContext, work_order: WorkOrder, reason: str, request=None) -> WorkOrder:
    wo = _lock(work_order)
    if wo.status not in CANCELLABLE_FROM:
        raise InvalidTransition(f"A {wo.status} work order cannot be cancelled.")
    if not reason.strip():
        raise exceptions.ValidationError({"reason": ["Give a reason for cancelling."]})
    old = wo.status
    wo.status, wo.cancelled_reason = WorkOrderStatus.CANCELLED, reason.strip()[:500]
    wo.save(update_fields=["status", "cancelled_reason", "updated_at"])
    Appointment.objects.filter(work_order=wo, status=Appointment.Status.CONFIRMED).update(
        status=Appointment.Status.CANCELLED, updated_at=timezone.now()
    )
    if wo.technician:
        _release_technician(wo.technician)
    _log(wo, tenant.membership.user, old, WorkOrderStatus.CANCELLED, note=reason)
    audit.record("work_order.cancelled", request=request, target=wo, changes={"reason": reason[:300]})
    _publish("work_order.status_changed", wo, old_status=old, new_status=WorkOrderStatus.CANCELLED)
    return wo


@transaction.atomic
def update_details(*, work_order: WorkOrder, data: dict, request=None) -> WorkOrder:
    wo = _lock(work_order)
    if wo.status in (WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED):
        raise DomainError("Completed or cancelled work orders cannot be edited.")
    changes = {}
    for field, value in data.items():
        if getattr(wo, field) != value:
            changes[field] = str(value)[:200]
            setattr(wo, field, value)
    if changes:
        wo.save()
        audit.record("work_order.updated", request=request, target=wo, changes=changes)
    return wo


# ---------------------------------------------------------------- evidence
@transaction.atomic
def add_evidence(
    *, tenant: TenantContext, work_order: WorkOrder, upload, kind: str, caption: str = "", request=None
) -> WorkOrderEvidence:
    wo = work_order
    can_manage = "work_orders.manage" in tenant.permissions
    if not can_manage:
        _require_assigned_technician(tenant, wo)
    if wo.status == WorkOrderStatus.CANCELLED:
        raise DomainError("Cancelled work orders cannot receive evidence.")
    photo_kinds = {
        WorkOrderEvidence.Kind.BEFORE_PHOTO,
        WorkOrderEvidence.Kind.AFTER_PHOTO,
        WorkOrderEvidence.Kind.SIGNATURE,
    }
    checked = validate_upload(upload, IMAGES if kind in photo_kinds else ALL_ALLOWED)
    evidence = WorkOrderEvidence(
        work_order=wo,
        kind=kind,
        original_name=checked.original_name,
        content_type=checked.content_type,
        size_bytes=checked.size,
        sha256=checked.sha256,
        caption=caption[:300],
        uploaded_by=tenant.membership.user,
    )
    evidence.file.save(checked.original_name, upload, save=False)
    evidence.save()
    audit.record(
        "work_order.evidence_added",
        request=request,
        target=wo,
        changes={"kind": kind, "file": checked.original_name, "sha256": checked.sha256},
    )
    return evidence


# ------------------------------------------------------------ confirmation
@transaction.atomic
def confirm(
    *,
    tenant: TenantContext,
    work_order: WorkOrder,
    signed_by: str,
    rating: int | None = None,
    comment: str = "",
    request=None,
) -> WorkOrder:
    """Customer sign-off, typically captured on the technician's device at the end of the visit."""
    wo = _lock(work_order)
    if "work_orders.manage" not in tenant.permissions:
        _require_assigned_technician(tenant, wo)
    if wo.status != WorkOrderStatus.COMPLETED:
        raise DomainError("The customer can only confirm a completed job.")
    if wo.customer_confirmed_at:
        raise Conflict("The customer has already confirmed this job.")
    if not signed_by.strip():
        raise exceptions.ValidationError({"signed_by": ["Enter the name of the person signing off."]})
    wo.customer_signed_by, wo.customer_confirmed_at = signed_by.strip()[:150], timezone.now()
    wo.customer_rating, wo.customer_comment = rating, comment.strip()[:2000]
    wo.save()
    _log(wo, tenant.membership.user, wo.status, wo.status, note=f"Customer confirmation by {wo.customer_signed_by}")
    audit.record(
        "work_order.customer_confirmed",
        request=request,
        target=wo,
        changes={"signed_by": wo.customer_signed_by, "rating": rating},
    )
    _publish("work_order.confirmed", wo, rating=rating)
    return wo


# -------------------------------------------------------------- appointments
def _check_slot(technician: Technician, starts_at, ends_at, *, exclude_id=None) -> list[str]:
    """Raises on hard conflicts; returns advisory warnings."""
    if ends_at <= starts_at:
        raise exceptions.ValidationError({"ends_at": ["The appointment must end after it starts."]})
    overlapping = Appointment.objects.filter(
        technician=technician, status=Appointment.Status.CONFIRMED, starts_at__lt=ends_at, ends_at__gt=starts_at
    ).exclude(pk=exclude_id)
    clash = overlapping.select_related("work_order").first()
    if clash:
        raise Conflict(
            f"{technician} is already booked for {clash.work_order.reference} "
            f"({timezone.localtime(clash.starts_at):%H:%M}–{timezone.localtime(clash.ends_at):%H:%M})."
        )
    blocks = TechnicianAvailability.objects.filter(technician=technician, starts_at__lt=ends_at, ends_at__gt=starts_at)
    if blocks.filter(type=TechnicianAvailability.Type.TIME_OFF).exists():
        raise exceptions.ValidationError({"starts_at": [f"{technician} has time off during this slot."]})
    warnings = []
    shifts = TechnicianAvailability.objects.filter(
        technician=technician, type=TechnicianAvailability.Type.SHIFT, starts_at__date=starts_at.date()
    )
    if shifts.exists() and not shifts.filter(starts_at__lte=starts_at, ends_at__gte=ends_at).exists():
        warnings.append("This slot falls outside the technician's shift.")
    day_jobs = (
        Appointment.objects.filter(
            technician=technician, status=Appointment.Status.CONFIRMED, starts_at__date=starts_at.date()
        )
        .exclude(pk=exclude_id)
        .count()
    )
    if day_jobs >= technician.max_daily_jobs:
        warnings.append(f"{technician} already has {day_jobs} job(s) that day (limit {technician.max_daily_jobs}).")
    return warnings


@transaction.atomic
def schedule(
    *, tenant: TenantContext, work_order: WorkOrder, starts_at, ends_at, notes: str = "", request=None
) -> tuple[Appointment, list[str]]:
    wo = _lock(work_order)
    if wo.technician is None:
        raise DomainError("Assign a technician before scheduling a visit.")
    if wo.status in (WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED):
        raise DomainError("Completed or cancelled work orders cannot be scheduled.")
    # Rescheduling replaces the current confirmed visit.
    current = Appointment.objects.filter(work_order=wo, status=Appointment.Status.CONFIRMED).first()
    warnings = _check_slot(wo.technician, starts_at, ends_at, exclude_id=current.pk if current else None)
    if current:
        current.status = Appointment.Status.CANCELLED
        current.save(update_fields=["status", "updated_at"])
    try:
        with transaction.atomic():
            appt = Appointment.objects.create(
                organization=wo.organization,
                work_order=wo,
                technician=wo.technician,
                starts_at=starts_at,
                ends_at=ends_at,
                notes=notes[:500],
            )
    except IntegrityError as exc:  # concurrent booking beat us to it; the exclusion constraint decides
        raise Conflict("That slot was just booked by someone else. Pick another time.") from exc
    wo.scheduled_start, wo.scheduled_end = starts_at, ends_at
    wo.save(update_fields=["scheduled_start", "scheduled_end", "updated_at"])
    audit.record(
        "work_order.scheduled",
        request=request,
        target=wo,
        changes={"starts_at": starts_at.isoformat(), "ends_at": ends_at.isoformat(), "rescheduled": bool(current)},
    )
    _publish("work_order.scheduled", wo)
    return appt, warnings


# ------------------------------------------------------------------ location
def record_location(*, tenant: TenantContext, lat, lng, accuracy_m=None) -> TechnicianLocation:
    tech = technician_for(tenant.membership.user, tenant.organization)
    if tech is None:
        raise exceptions.PermissionDenied("Only technicians share their location.")
    if not tech.location_sharing_enabled:
        raise Conflict("Location sharing is turned off in your profile.")
    active = WorkOrder.objects.filter(technician=tech, status__in=FIELD_ACTIVE_STATUSES).order_by("-updated_at").first()
    if active is None:
        raise Conflict("Location is only recorded while you are travelling to or working on a job.")
    return TechnicianLocation.objects.create(
        technician=tech, work_order=active, lat=lat, lng=lng, accuracy_m=accuracy_m
    )


def purge_old_locations() -> int:
    cutoff = timezone.now() - timedelta(days=LOCATION_RETENTION_DAYS)
    deleted, _ = TechnicianLocation.objects.filter(recorded_at__lt=cutoff).delete()
    return deleted
