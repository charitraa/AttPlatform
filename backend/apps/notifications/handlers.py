"""
Domain events → notifications and real-time cache invalidation.

All handlers run after commit, so nobody is told about a change that rolled back.
The person who acted (`actor_id` in the payload) is never notified about their own action.
"""

from apps.core import events

from . import realtime
from .models import NotificationType as T
from .services import members_with_permission, notify


def _ticket(event):
    from apps.tickets.models import Ticket

    return (
        Ticket.objects.select_related("organization", "assigned_agent", "assigned_technician", "customer")
        .filter(pk=event.payload["ticket_id"])
        .first()
    )


def _work_order(event):
    from apps.field_service.models import WorkOrder

    return (
        WorkOrder.objects.select_related("organization", "technician__user", "created_by", "ticket__assigned_agent")
        .filter(pk=event.payload["work_order_id"])
        .first()
    )


def _has_work_order(ticket) -> bool:
    from apps.field_service.models import ACTIVE_WORK_ORDER_STATUSES, WorkOrder

    return WorkOrder.objects.filter(
        ticket=ticket, technician__user=ticket.assigned_technician, status__in=ACTIVE_WORK_ORDER_STATUSES
    ).exists()


def _user(user_id):
    from apps.accounts.models import User

    return User.objects.filter(pk=user_id).first() if user_id else None


# --------------------------------------------------------------- invalidation
@events.subscribe("ticket.created", on_commit=True)
@events.subscribe("ticket.updated", on_commit=True)
@events.subscribe("ticket.status_changed", on_commit=True)
@events.subscribe("ticket.assigned", on_commit=True)
@events.subscribe("ticket.commented", on_commit=True)
def push_ticket_change(event: events.Event) -> None:
    p = event.payload
    data = {"ticket_id": p["ticket_id"], "change": event.name}
    realtime.push(realtime.staff_group(p["organization_id"]), "ticket.changed", **data)
    # Technicians only see tickets assigned to them, so they get their own copy.
    ticket = _ticket(event)
    if ticket and ticket.assigned_technician_id:
        realtime.push(realtime.user_group(ticket.assigned_technician_id, ticket.organization_id), "ticket.changed", **data)


@events.subscribe("work_order.created", on_commit=True)
@events.subscribe("work_order.assigned", on_commit=True)
@events.subscribe("work_order.status_changed", on_commit=True)
@events.subscribe("work_order.declined", on_commit=True)
@events.subscribe("work_order.scheduled", on_commit=True)
@events.subscribe("work_order.confirmed", on_commit=True)
def push_work_order_change(event: events.Event) -> None:
    p = event.payload
    data = {"work_order_id": p["work_order_id"], "change": event.name}
    realtime.push(realtime.dispatch_group(p["organization_id"]), "work_order.changed", **data)
    for key in ("technician_user_id", "previous_technician_user_id"):
        if p.get(key):
            realtime.push(realtime.user_group(p[key], p["organization_id"]), "work_order.changed", **data)
    if "technician_user_id" not in p:
        wo = _work_order(event)
        if wo and wo.technician:
            realtime.push(realtime.user_group(wo.technician.user_id, wo.organization_id), "work_order.changed", **data)


@events.subscribe("sla.warning", on_commit=True)
@events.subscribe("sla.breached", on_commit=True)
@events.subscribe("sla.escalated", on_commit=True)
def push_sla_change(event: events.Event) -> None:
    p = event.payload
    realtime.push(
        realtime.staff_group(p["organization_id"]),
        "sla.changed",
        ticket_id=p["ticket_id"],
        metric=p["metric"],
        change=event.name,
    )


# ---------------------------------------------------------------- tickets
@events.subscribe("ticket.assigned", on_commit=True)
def notify_ticket_assignee(event: events.Event) -> None:
    ticket = _ticket(event)
    if ticket is None:
        return
    p = event.payload
    fields = set(p.get("fields") or [])
    recipients = []
    if "assigned_agent" in fields and ticket.assigned_agent:
        recipients.append(ticket.assigned_agent)
    if "assigned_technician" in fields and ticket.assigned_technician and not _has_work_order(ticket):
        recipients.append(ticket.assigned_technician)  # work-order assignments notify on their own
    notify(
        organization=ticket.organization,
        recipients=recipients,
        type=T.TICKET_ASSIGNED,
        title=f"{ticket.reference} assigned to you",
        body=f"{ticket.title} · {ticket.customer.name} · {ticket.get_priority_display()} priority",
        link=f"/tickets/{ticket.id}",
        data={"ticket_id": str(ticket.id)},
        exclude_user_id=p.get("actor_id"),
    )


@events.subscribe("ticket.commented", on_commit=True)
def notify_customer_reply(event: events.Event) -> None:
    p = event.payload
    if not p.get("by_customer"):
        return
    ticket = _ticket(event)
    if ticket is None or not ticket.assigned_agent:
        return
    notify(
        organization=ticket.organization,
        recipients=[ticket.assigned_agent],
        type=T.CUSTOMER_REPLY,
        title=f"{ticket.customer.name} replied on {ticket.reference}",
        body=ticket.title,
        link=f"/tickets/{ticket.id}",
        data={"ticket_id": str(ticket.id), "comment_id": p.get("comment_id")},
        exclude_user_id=p.get("actor_id"),
    )


@events.subscribe("ticket.status_changed", on_commit=True)
def notify_status_change(event: events.Event) -> None:
    p = event.payload
    ticket = _ticket(event)
    if ticket is None:
        return
    if p.get("new_status") == "escalated" and not p.get("reason"):  # SLA escalations are covered by sla.breached
        notify(
            organization=ticket.organization,
            recipients=[ticket.assigned_agent, *members_with_permission(ticket.organization, "tickets.assign")],
            type=T.TICKET_ESCALATED,
            title=f"{ticket.reference} was escalated",
            body=ticket.title,
            link=f"/tickets/{ticket.id}",
            data={"ticket_id": str(ticket.id)},
            exclude_user_id=p.get("actor_id"),
        )
    elif p.get("new_status") == "reopened" and p.get("by_customer") and ticket.assigned_agent:
        notify(
            organization=ticket.organization,
            recipients=[ticket.assigned_agent],
            type=T.TICKET_REOPENED,
            title=f"{ticket.customer.name} reopened {ticket.reference}",
            body="The customer says the problem isn't solved.",
            link=f"/tickets/{ticket.id}",
            data={"ticket_id": str(ticket.id)},
            exclude_user_id=p.get("actor_id"),
        )


# -------------------------------------------------------------------- SLA
@events.subscribe("sla.warning", on_commit=True)
@events.subscribe("sla.breached", on_commit=True)
def notify_sla(event: events.Event) -> None:
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    ticket = _ticket(event)
    if ticket is None:
        return
    p, breached = event.payload, event.name == "sla.breached"
    metric = "first response" if p["metric"] == "response" else "resolution"
    managers = members_with_permission(ticket.organization, "tickets.assign")
    # Warnings go to whoever owns the ticket (managers only if nobody does); breaches always reach managers.
    recipients = [ticket.assigned_agent] if ticket.assigned_agent else []
    if breached or not recipients:
        recipients += managers
    due = parse_datetime(p["due_at"])
    when = timezone.localtime(due).strftime("%d %b %H:%M") if due else ""
    notify(
        organization=ticket.organization,
        recipients=recipients,
        type=T.SLA_BREACHED if breached else T.SLA_WARNING,
        title=(f"{ticket.reference} breached its {metric} target" if breached
               else f"{ticket.reference} is close to its {metric} deadline"),
        body=f"{ticket.title} · {ticket.get_priority_display()} · due {when}",
        link=f"/tickets/{ticket.id}",
        data={"ticket_id": str(ticket.id), "metric": p["metric"]},
    )


# ------------------------------------------------------------ work orders
@events.subscribe("work_order.assigned", on_commit=True)
def notify_work_order_assignee(event: events.Event) -> None:
    p = event.payload
    if not p.get("technician_user_id"):
        return
    wo = _work_order(event)
    if wo is None:
        return
    when = ""
    if wo.scheduled_start:
        from django.utils import timezone

        when = f" · {timezone.localtime(wo.scheduled_start):%d %b %H:%M}"
    notify(
        organization=wo.organization,
        recipients=[_user(p["technician_user_id"])],
        type=T.WORK_ORDER_ASSIGNED,
        title=f"New job {wo.reference}",
        body=f"{wo.title} · {wo.service_address}{when}",
        link=f"/work-orders/{wo.id}",
        data={"work_order_id": str(wo.id)},
        exclude_user_id=p.get("actor_id"),
    )


@events.subscribe("work_order.status_changed", on_commit=True)
@events.subscribe("work_order.declined", on_commit=True)
def notify_work_order_outcome(event: events.Event) -> None:
    p = event.payload
    wo = _work_order(event)
    if wo is None:
        return
    if event.name == "work_order.declined":
        title, body = f"{wo.reference} was handed back", p.get("reason", "")
        recipients = [wo.created_by, *members_with_permission(wo.organization, "work_orders.manage")]
    elif p.get("new_status") == "completed":
        title, body = f"{wo.reference} completed", wo.completion_summary[:300]
        recipients = [wo.created_by, wo.ticket.assigned_agent if wo.ticket else None]
    elif p.get("new_status") == "cancelled":
        title, body = f"{wo.reference} was cancelled", wo.cancelled_reason
        recipients = [_user(p.get("technician_user_id"))]
    else:
        return
    notify(
        organization=wo.organization,
        recipients=recipients,
        type=T.WORK_ORDER_UPDATED,
        title=title,
        body=body,
        link=f"/work-orders/{wo.id}",
        data={"work_order_id": str(wo.id), "status": p.get("new_status", "created")},
        exclude_user_id=p.get("actor_id"),
    )
