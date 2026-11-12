"""Domain-event subscribers: AI reacts to ticket events without the tickets app knowing about it."""

from apps.core import events


@events.subscribe("ticket.created", on_commit=True)
def triage_new_ticket(event: events.Event) -> None:
    from apps.tickets.models import Ticket

    from .services import TRIAGE_KINDS, ai_enabled, org_setting, request_ticket_analysis

    ticket = Ticket.objects.select_related("organization").filter(pk=event.payload["ticket_id"]).first()
    if ticket is None or not ai_enabled(ticket.organization):
        return
    kinds = [
        k
        for k in TRIAGE_KINDS
        if not (k == "routing" and org_setting(ticket.organization, "routing_policy", "recommend") == "manual")
    ]
    request_ticket_analysis(ticket=ticket, kinds=kinds, trigger="ticket_created")


@events.subscribe("ticket.status_changed", on_commit=True)
def draft_knowledge_from_closed_ticket(event: events.Event) -> None:
    if event.payload.get("new_status") != "closed":
        return
    from apps.tickets.models import Ticket

    from .services import ai_enabled, request_ticket_analysis

    ticket = Ticket.objects.select_related("organization").filter(pk=event.payload["ticket_id"]).first()
    if ticket is None or not ticket.resolution_notes or not ai_enabled(ticket.organization):
        return
    request_ticket_analysis(ticket=ticket, kinds=["knowledge_extraction"], trigger="ticket_closed")
