"""
SLA reacts to ticket events synchronously, inside the ticket's transaction, so a
ticket and its SLA clock are always committed together.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.core import events
from apps.organizations.models import Organization

TICKET_EVENTS = ("ticket.created", "ticket.updated", "ticket.status_changed", "ticket.assigned", "ticket.commented")


def _sync(event: events.Event) -> None:
    from .services import sync_ticket

    sync_ticket(event.payload["ticket_id"])


for _name in TICKET_EVENTS:
    events.subscribe(_name)(_sync)


@receiver(post_save, sender=Organization, dispatch_uid="sla.default_policy")
def create_default_policy(sender, instance: Organization, created: bool, **kwargs):
    if created:
        from .services import ensure_default_policy

        ensure_default_policy(instance)
