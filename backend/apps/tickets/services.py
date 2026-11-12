"""
Write-side ticket logic. Every mutation:
  * runs in a transaction,
  * records field-level TicketHistory (the user-facing timeline) and an AuditLog entry,
  * publishes a domain event for other modules (AI, SLA, notifications) on commit.
"""


from django.db import transaction
from django.utils import timezone
from rest_framework import exceptions

from apps.audit import services as audit
from apps.core import events
from apps.core.exceptions import DomainError, InvalidTransition
from apps.core.uploads import validate_upload
from apps.customers.models import Customer
from apps.organizations.catalog import RoleCode
from apps.organizations.models import Membership
from apps.organizations.services import next_sequence_value
from apps.organizations.tenancy import TenantContext

from .lifecycle import REQUIRES_RESOLUTION, allowed_transitions
from .models import Ticket, TicketAssignment, TicketAttachment, TicketComment, TicketHistory, TicketStatus
from .selectors import can_see_internal, customer_ids_for_user, is_staff_actor

AGENT_ROLES = frozenset({RoleCode.SUPPORT_AGENT, RoleCode.OPS_MANAGER, RoleCode.ORG_ADMIN, RoleCode.SUPER_ADMIN})
TECHNICIAN_ROLES = frozenset({RoleCode.FIELD_TECHNICIAN})
UNSET = object()  # "leave this assignee unchanged"

# ------------------------------------------------------------------------ helpers
def _history(ticket, actor, event, *, field="", old=None, new=None, internal=False, actor_type=None):
    """`actor_type` defaults to user (with an actor) or system (without); pass "ai" for AI-made changes."""
    TicketHistory.objects.create(
        ticket=ticket,
        actor=actor,
        actor_type=actor_type or (TicketHistory.ActorType.USER if actor else TicketHistory.ActorType.SYSTEM),
        event=event,
        field=field,
        old_value=old,
        new_value=new,
        internal=internal,
    )


def _display(value):
    """JSON-safe representation of a field value for history."""
    if value is None or isinstance(value, (str, int, float, bool, list)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "pk"):
        # Users are labelled by name (str() of a user is their email).
        return {"id": str(value.pk), "label": getattr(value, "full_name", None) or str(value)}
    return str(value)


def _publish(name: str, ticket: Ticket, **extra) -> None:
    events.publish(name, organization_id=str(ticket.organization_id), ticket_id=str(ticket.id), **extra)


def _ensure_staff(tenant: TenantContext) -> None:
    if not is_staff_actor(tenant):
        raise exceptions.PermissionDenied("This action is only available to support staff.")


# ------------------------------------------------------------------------ create
@transaction.atomic
def create_ticket(*, tenant: TenantContext, data: dict, request=None) -> Ticket:
    """
    `data` is validated by the serializer (all FKs already scoped to the organization).
    Customer-portal users can only raise tickets for their own customer account; their
    priority comes from the category default (staff triage it).
    """
    user, org = tenant.membership.user, tenant.organization
    customer, contact, asset, category = (
        data.get("customer"),
        data.get("contact"),
        data.get("asset"),
        data.get("category"),
    )
    staff = is_staff_actor(tenant)

    if customer is None:
        if staff:
            raise exceptions.ValidationError({"customer": ["Choose the customer this ticket is for."]})
        own = list(Customer.objects.filter(id__in=customer_ids_for_user(user, org), archived_at__isnull=True)[:2])
        if len(own) != 1:
            raise exceptions.ValidationError(
                {"customer": ["Your account isn't linked to a single customer. Contact support."]}
            )
        customer = own[0]

    if not staff:
        if not customer_ids_for_user(user, org).filter(customer_id=customer.id).exists():
            raise exceptions.PermissionDenied("You can only raise tickets for your own customer account.")
        contact = contact or customer.contacts.filter(user=user).first()
    if contact and contact.customer_id != customer.id:
        raise exceptions.ValidationError({"contact": ["This contact does not belong to the selected customer."]})
    if asset and asset.customer_id != customer.id:
        raise exceptions.ValidationError({"asset": ["This asset does not belong to the selected customer."]})

    if staff and data.get("priority"):
        priority, source = data["priority"], Ticket.PrioritySource.MANUAL
    elif category:
        priority, source = category.default_priority, Ticket.PrioritySource.POLICY
    else:
        priority, source = Ticket.priority.field.default, Ticket.PrioritySource.POLICY

    ticket = Ticket.objects.create(
        organization=org,
        number=next_sequence_value(org, "ticket"),
        title=data["title"].strip(),
        description=data["description"].strip(),
        priority=priority,
        priority_source=source,
        category=category,
        channel=data.get("channel") or (Ticket.Channel.STAFF if staff else Ticket.Channel.PORTAL),
        tags=sorted({t.strip().lower() for t in data.get("tags", []) if t.strip()}),
        customer=customer,
        contact=contact,
        asset=asset,
        created_by=user,
    )
    _history(ticket, user, "created", new={"status": ticket.status, "priority": ticket.priority})
    audit.record("ticket.created", request=request, target=ticket, changes={"number": ticket.reference})
    _publish("ticket.created", ticket)
    return ticket


# ------------------------------------------------------------------------ update
EDITABLE_FIELDS = ("title", "description", "priority", "category", "tags", "contact", "asset")


@transaction.atomic
def update_ticket(*, tenant: TenantContext, ticket: Ticket, data: dict, request=None) -> Ticket:
    _ensure_staff(tenant)
    ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
    if ticket.archived_at:
        raise DomainError("Archived tickets cannot be edited. Unarchive it first.")
    user = tenant.membership.user
    contact, asset = data.get("contact", ticket.contact), data.get("asset", ticket.asset)
    if contact and contact.customer_id != ticket.customer_id:
        raise exceptions.ValidationError({"contact": ["This contact does not belong to the ticket's customer."]})
    if asset and asset.customer_id != ticket.customer_id:
        raise exceptions.ValidationError({"asset": ["This asset does not belong to the ticket's customer."]})
    if "tags" in data:
        data["tags"] = sorted({t.strip().lower() for t in data["tags"] if t.strip()})

    changes = {}
    for field in EDITABLE_FIELDS:
        if field not in data:
            continue
        old, new = getattr(ticket, field), data[field]
        if old != new:
            changes[field] = {"from": _display(old), "to": _display(new)}
            setattr(ticket, field, new)
            _history(ticket, user, "field_changed", field=field, old=_display(old), new=_display(new))
    if "priority" in changes:
        ticket.priority_source = Ticket.PrioritySource.MANUAL
    if changes:
        ticket.save()
        audit.record("ticket.updated", request=request, target=ticket, changes=changes)
        _publish("ticket.updated", ticket, fields=sorted(changes))
    return ticket


# -------------------------------------------------------------------- transitions
@transaction.atomic
def transition_ticket(
    *,
    tenant: TenantContext,
    ticket: Ticket,
    to_status: str,
    note: str = "",
    resolution_notes: str | None = None,
    request=None,
) -> Ticket:
    ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
    user, staff = tenant.membership.user, is_staff_actor(tenant)
    if ticket.archived_at:
        raise DomainError("Archived tickets cannot change status.")
    if to_status not in allowed_transitions(ticket.status, is_staff=staff):
        raise InvalidTransition(f"Cannot move a ticket from '{ticket.status}' to '{to_status}'.")

    if to_status in REQUIRES_RESOLUTION:
        notes = (resolution_notes if resolution_notes is not None else ticket.resolution_notes).strip()
        if not notes:
            raise exceptions.ValidationError({"resolution_notes": ["Describe how the issue was resolved."]})
        if notes != ticket.resolution_notes:
            _history(ticket, user, "field_changed", field="resolution_notes", old=ticket.resolution_notes, new=notes)
            ticket.resolution_notes = notes

    old_status, now = ticket.status, timezone.now()
    ticket.status = to_status
    if to_status == TicketStatus.RESOLVED:
        ticket.resolved_at = now
    elif to_status == TicketStatus.CLOSED:
        ticket.closed_at = now
        ticket.resolved_at = ticket.resolved_at or now
        if not staff:
            ticket.customer_confirmed_at = now  # customer confirmed the resolution
    elif to_status == TicketStatus.REOPENED:
        ticket.resolved_at = ticket.closed_at = ticket.customer_confirmed_at = None
    ticket.save()

    _history(ticket, user, "status_changed", field="status", old=old_status, new=to_status)
    if note.strip():
        add_comment(
            tenant=tenant,
            ticket=ticket,
            body=note,
            visibility=TicketComment.Visibility.INTERNAL if staff else TicketComment.Visibility.PUBLIC,
            request=request,
            _skip_status_side_effects=True,
        )
    audit.record(
        "ticket.status_changed",
        request=request,
        target=ticket,
        changes={"status": {"from": old_status, "to": to_status}},
    )
    _publish(
        "ticket.status_changed",
        ticket,
        old_status=old_status,
        new_status=to_status,
        actor_id=str(user.pk),
        by_customer=not staff,
    )
    return ticket


@transaction.atomic
def escalate_for_sla(*, ticket: Ticket, reason: str) -> Ticket | None:
    """
    System escalation (SLA breach). Follows the staff transition table; returns None
    when the ticket is archived or its status can't move to Escalated (e.g. already
    escalated, or waiting on the customer).
    """
    ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
    if ticket.archived_at or TicketStatus.ESCALATED not in allowed_transitions(ticket.status, is_staff=True):
        return None
    old_status = ticket.status
    ticket.status = TicketStatus.ESCALATED
    ticket.save(update_fields=["status", "updated_at"])
    _history(ticket, None, "status_changed", field="status", old=old_status, new=TicketStatus.ESCALATED)
    audit.record(
        "ticket.status_changed",
        organization=ticket.organization,
        target=ticket,
        changes={"status": {"from": old_status, "to": TicketStatus.ESCALATED}, "reason": reason},
        actor_type="system",
    )
    _publish("ticket.status_changed", ticket, old_status=old_status, new_status=TicketStatus.ESCALATED, reason=reason)
    return ticket


def escalate_ticket(*, tenant: TenantContext, ticket: Ticket, reason: str, request=None) -> Ticket:
    _ensure_staff(tenant)
    if not reason.strip():
        raise exceptions.ValidationError({"reason": ["Explain why the ticket is being escalated."]})
    return transition_ticket(
        tenant=tenant,
        ticket=ticket,
        to_status=TicketStatus.ESCALATED,
        note=f"Escalated: {reason.strip()}",
        request=request,
    )


# --------------------------------------------------------------------- assignment
def _eligible_member(org, user_id, roles: frozenset[str], label: str):
    membership = (
        Membership.objects.filter(organization=org, user_id=user_id, is_active=True, role__code__in=roles)
        .select_related("user")
        .first()
    )
    if membership is None:
        raise exceptions.ValidationError({label: [f"Choose an active {label} from this organization."]})
    return membership.user


@transaction.atomic
def assign_ticket(
    *,
    tenant: TenantContext,
    ticket: Ticket,
    agent_id=UNSET,
    technician_id=UNSET,
    source: str = TicketAssignment.Source.MANUAL,
    request=None,
) -> Ticket:
    return assign(organization=tenant.organization, actor=tenant.membership.user, ticket=ticket, agent_id=agent_id,
                  technician_id=technician_id, source=source, request=request)


@transaction.atomic
def assign(*, organization, actor, ticket: Ticket, agent_id=UNSET, technician_id=UNSET,
           source: str = TicketAssignment.Source.MANUAL, request=None) -> Ticket:
    """Assignment core. `actor` may be None for policy-driven automatic (AI) assignment."""
    ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
    org = organization
    if ticket.archived_at or ticket.status == TicketStatus.CLOSED:
        raise DomainError("Closed or archived tickets cannot be reassigned.")

    changed = {}
    for role, field, user_id, roles in (
        (TicketAssignment.Role.AGENT, "assigned_agent", agent_id, AGENT_ROLES),
        (TicketAssignment.Role.TECHNICIAN, "assigned_technician", technician_id, TECHNICIAN_ROLES),
    ):
        if user_id is UNSET:
            continue
        new_user = _eligible_member(org, user_id, roles, role) if user_id else None
        old_user = getattr(ticket, field)
        if old_user == new_user:
            continue
        TicketAssignment.objects.filter(ticket=ticket, role=role, unassigned_at__isnull=True).update(
            unassigned_at=timezone.now()
        )
        if new_user:
            TicketAssignment.objects.create(
                ticket=ticket, assignee=new_user, role=role, source=source, assigned_by=actor
            )
        setattr(ticket, field, new_user)
        changed[field] = {"from": _display(old_user), "to": _display(new_user)}
        _history(
            ticket,
            actor,
            "assigned",
            field=field,
            old=_display(old_user),
            new=_display(new_user),
            actor_type="ai" if source == TicketAssignment.Source.AI_AUTO else None,
        )

    if not changed:
        return ticket
    # Picking up a fresh ticket moves it to "assigned" automatically.
    if ticket.assigned_agent and ticket.status in (TicketStatus.NEW, TicketStatus.OPEN, TicketStatus.REOPENED):
        _history(ticket, actor, "status_changed", field="status", old=ticket.status, new=TicketStatus.ASSIGNED)
        ticket.status = TicketStatus.ASSIGNED
    ticket.save()
    audit.record(
        "ticket.assigned", request=request, actor=actor, organization=org, target=ticket, changes=changed,
        actor_type="ai" if source == TicketAssignment.Source.AI_AUTO else None,
    )
    _publish(
        "ticket.assigned",
        ticket,
        fields=sorted(changed),
        agent_id=str(ticket.assigned_agent_id or "") or None,
        technician_id=str(ticket.assigned_technician_id or "") or None,
        actor_id=str(actor.pk) if actor else None,
    )
    return ticket


# ----------------------------------------------------------------------- comments
@transaction.atomic
def add_comment(
    *,
    tenant: TenantContext,
    ticket: Ticket,
    body: str,
    visibility: str,
    request=None,
    _skip_status_side_effects: bool = False,
) -> TicketComment:
    user, staff = tenant.membership.user, is_staff_actor(tenant)
    body = body.strip()
    if not body:
        raise exceptions.ValidationError({"body": ["Write a message."]})
    if visibility == TicketComment.Visibility.INTERNAL and not can_see_internal(tenant):
        raise exceptions.PermissionDenied("You cannot write internal notes.")
    if ticket.status == TicketStatus.CLOSED and not staff:
        raise DomainError("This ticket is closed. Reopen it or raise a new ticket.")

    comment = TicketComment.objects.create(
        ticket=ticket,
        author=user,
        body=body,
        visibility=visibility,
        source=TicketComment.Source.STAFF if staff else TicketComment.Source.CUSTOMER,
    )
    internal = visibility == TicketComment.Visibility.INTERNAL
    _history(
        ticket, user, "commented", new={"comment_id": str(comment.id), "visibility": visibility}, internal=internal
    )

    update_fields = ["updated_at"]
    if staff and not internal and ticket.first_response_at is None:
        ticket.first_response_at = comment.created_at
        update_fields.append("first_response_at")
    if not staff and not _skip_status_side_effects and ticket.status == TicketStatus.PENDING_CUSTOMER:
        # The customer answered: the ball is back with the support team.
        new_status = TicketStatus.IN_PROGRESS if ticket.assigned_agent_id else TicketStatus.OPEN
        _history(ticket, user, "status_changed", field="status", old=ticket.status, new=new_status)
        ticket.status = new_status
        update_fields.append("status")
    ticket.save(update_fields=update_fields)
    _publish(
        "ticket.commented",
        ticket,
        comment_id=str(comment.id),
        visibility=visibility,
        by_customer=not staff,
        actor_id=str(user.pk),
    )
    return comment


# -------------------------------------------------------------------- attachments
@transaction.atomic
def add_attachment(
    *, tenant: TenantContext, ticket: Ticket, upload, visibility: str, comment=None, request=None
) -> TicketAttachment:
    user = tenant.membership.user
    if visibility == TicketComment.Visibility.INTERNAL and not can_see_internal(tenant):
        raise exceptions.PermissionDenied("You cannot add internal attachments.")
    if ticket.archived_at:
        raise DomainError("Archived tickets cannot receive attachments.")

    checked = validate_upload(upload)
    original_name = checked.original_name

    attachment = TicketAttachment(
        ticket=ticket,
        comment=comment,
        original_name=original_name,
        content_type=checked.content_type,
        size_bytes=checked.size,
        sha256=checked.sha256,
        visibility=visibility,
        uploaded_by=user,
    )
    attachment.file.save(original_name, upload, save=False)
    attachment.save()
    _history(
        ticket,
        user,
        "attachment_added",
        new={"attachment_id": str(attachment.id), "name": original_name},
        internal=visibility == TicketComment.Visibility.INTERNAL,
    )
    audit.record(
        "ticket.attachment_added",
        request=request,
        target=ticket,
        changes={"attachment": original_name, "sha256": attachment.sha256, "size": upload.size},
    )
    return attachment


# ----------------------------------------------------------------------- archiving
@transaction.atomic
def set_archived(*, tenant: TenantContext, ticket: Ticket, archived: bool, request=None) -> Ticket:
    ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
    if bool(ticket.archived_at) == archived:
        return ticket
    ticket.archived_at = timezone.now() if archived else None
    ticket.save(update_fields=["archived_at", "updated_at"])
    _history(ticket, tenant.membership.user, "archived" if archived else "unarchived", internal=True)
    audit.record("ticket.archived" if archived else "ticket.unarchived", request=request, target=ticket)
    return ticket


# ----------------------------------------------------------- AI-driven changes
AI_APPLICABLE_FIELDS = {"category", "priority"}


@transaction.atomic
def apply_field_change(*, ticket: Ticket, field: str, value, actor=None, request=None, reason: str = "") -> Ticket:
    """
    Apply a single field value that originated from an AI recommendation.

    `actor=None` means the change was applied automatically under an explicit org
    policy (history and audit record actor_type=ai). With an actor, a person
    accepted the recommendation. Either way `priority_source` becomes "ai".
    """
    if field not in AI_APPLICABLE_FIELDS:
        raise ValueError(f"AI may not change '{field}'.")
    ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
    if ticket.archived_at or ticket.status == TicketStatus.CLOSED:
        raise DomainError("Closed or archived tickets cannot be changed.")
    old = getattr(ticket, field)
    if old == value:
        return ticket
    setattr(ticket, field, value)
    if field == "priority":
        ticket.priority_source = Ticket.PrioritySource.AI
    ticket.save()
    actor_type = None if actor else TicketHistory.ActorType.AI
    _history(ticket, actor, "field_changed", field=field, old=_display(old), new=_display(value), actor_type=actor_type)
    audit.record(
        "ticket.ai_change_applied", request=request, actor=actor, organization=ticket.organization, target=ticket,
        actor_type="user" if actor else "ai",
        changes={field: {"from": _display(old), "to": _display(value)}, "reason": reason[:300]},
    )
    _publish("ticket.updated", ticket, fields=[field], by_ai=actor is None)
    return ticket
