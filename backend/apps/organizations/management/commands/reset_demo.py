"""
Rebuild the demo organization's activity around today (development only).

    python manage.py reset_demo [--org acme] [--count 45] [--seed 11]

Deletes the organization's tickets, work orders, notifications, feedback and webhook
traffic, then re-seeds tickets (timelines drawn against the real SLA targets) and
field service, rebuilds every SLA clock from its timeline, and adds customer ratings
and a few in-app notifications. Users, customers, assets, categories, SLA policies,
knowledge articles and integrations are kept. Runs with domain events muted, so it
sends no email, webhooks or AI requests.
"""

import random
from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.core import events
from apps.customers.models import CustomerContact
from apps.field_service.models import TechnicianAvailability, TechnicianLocation, WorkOrder
from apps.integrations.models import WebhookDelivery, WebhookEvent
from apps.notifications.models import Notification, NotificationType
from apps.notifications.services import members_with_permission
from apps.organizations.catalog import RoleCode
from apps.organizations.models import Membership, Organization, OrganizationSequence
from apps.portal.models import CustomerFeedback
from apps.sla import services as sla_services
from apps.sla.models import MetricStatus
from apps.tickets.models import Ticket, TicketStatus

COMMENTS = {
    5: ["Quick and professional, thank you!", "Fixed on the first visit.", ""],
    4: ["Good service, a bit slow to start.", ""],
    3: ["Solved, but it took a few days.", ""],
    2: ["Had to chase for updates."],
    1: ["The problem came back the next day."],
}


class Command(BaseCommand):
    help = "Delete and re-seed the demo organization's tickets and jobs, dated around today (dev only)."

    def add_arguments(self, parser):
        parser.add_argument("--org", default="acme")
        parser.add_argument("--count", type=int, default=45)
        parser.add_argument("--seed", type=int, default=11)

    def handle(self, *args, org, count, seed, **options):
        if settings.ENVIRONMENT == "production":
            raise CommandError("reset_demo must not run in production.")
        organization = Organization.objects.filter(slug=org).first()
        if organization is None:
            raise CommandError(f"Organization '{org}' not found. Run `manage.py seed_demo` first.")
        rng = random.Random(seed)  # noqa: S311 - demo data
        with events.muted(), transaction.atomic():
            removed = self._wipe(organization)
            call_command("seed_tickets", org=org, count=count, seed=seed, stdout=self.stdout)
            call_command("seed_field_service", org=org, stdout=self.stdout)
            now = timezone.now()
            tickets = list(Ticket.objects.filter(organization=organization).select_related("customer"))
            for t in tickets:  # field service moved some tickets on; rebuild every clock once more
                sla_services.restamp(t, now=now)
            ratings = self._feedback(organization, tickets, rng, now)
            notes = self._notifications(organization, now)
        sla = sla_services.compliance(organization, start=now - timedelta(days=31), end=now)
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo reset for '{org}': removed {removed} tickets; seeded {len(tickets)} tickets, "
                f"{WorkOrder.objects.filter(organization=organization).count()} work orders, {ratings} ratings, "
                f"{notes} notifications. SLA resolution compliance (30 days): "
                f"{round((sla['resolution_compliance'] or 0) * 100)} %."
            )
        )

    def _wipe(self, org) -> int:
        WebhookDelivery.objects.filter(endpoint__integration__organization=org).delete()
        WebhookEvent.objects.filter(organization=org).delete()
        Notification.objects.filter(organization=org).delete()
        CustomerFeedback.objects.filter(organization=org).delete()
        TechnicianLocation.objects.filter(technician__organization=org).delete()
        TechnicianAvailability.objects.filter(technician__organization=org).delete()
        WorkOrder.objects.filter(organization=org).delete()
        tickets = Ticket.objects.filter(organization=org)
        count = tickets.count()
        tickets.delete()
        OrganizationSequence.objects.filter(organization=org, key__in=["ticket", "work_order"]).update(value=0)
        return count

    def _feedback(self, org, tickets, rng, now) -> int:
        portal = Membership.objects.filter(organization=org, role__code=RoleCode.CUSTOMER, is_active=True).first()
        portal_customers = (
            set(CustomerContact.objects.filter(user=portal.user).values_list("customer_id", flat=True))
            if portal
            else set()
        )
        made = 0
        for t in tickets:
            if t.status != TicketStatus.CLOSED or rng.random() > 0.7:
                continue
            late = getattr(getattr(t, "sla", None), "resolution_status", "") == MetricStatus.BREACHED
            rating = rng.choices([5, 4, 3, 2, 1], weights=[30, 30, 20, 12, 8] if late else [55, 30, 10, 4, 1])[0]
            when = min(now, (t.closed_at or now) + timedelta(hours=rng.uniform(1, 20)))
            fb = CustomerFeedback.objects.create(
                organization=org,
                customer=t.customer,
                ticket=t,
                rating=rating,
                comment=rng.choice(COMMENTS[rating]),
                submitted_by=portal.user if portal and t.customer_id in portal_customers else None,
            )
            CustomerFeedback.objects.filter(pk=fb.pk).update(created_at=when)
            made += 1
        return made

    def _notifications(self, org, now) -> int:
        made = 0

        def add(user, type_, title, body, ticket, at, read):
            nonlocal made
            n = Notification.objects.create(
                organization=org,
                recipient=user,
                type=type_,
                title=title,
                body=body,
                link=f"/tickets/{ticket.id}",
                data={"ticket_id": str(ticket.id)},
                read_at=at + timedelta(minutes=30) if read else None,
            )
            Notification.objects.filter(pk=n.pk).update(created_at=at)
            made += 1

        open_tickets = (
            Ticket.objects.filter(organization=org, assigned_agent__isnull=False)
            .exclude(status__in=[TicketStatus.RESOLVED, TicketStatus.CLOSED])
            .select_related("assigned_agent", "customer", "sla")
        )
        for t in open_tickets.order_by("-created_at")[:12]:
            at = t.first_response_at or t.created_at
            add(
                t.assigned_agent,
                NotificationType.TICKET_ASSIGNED,
                f"{t.reference} assigned to you",
                f"{t.title} · {t.customer.name} · {t.get_priority_display()} priority",
                t,
                at,
                now - at > timedelta(days=2),
            )
        managers = members_with_permission(org, "tickets.assign")
        for t in open_tickets:
            sla = getattr(t, "sla", None)
            if sla and sla.resolution_status == MetricStatus.WARNING:
                add(
                    t.assigned_agent,
                    NotificationType.SLA_WARNING,
                    f"{t.reference} is close to its resolution deadline",
                    f"{t.title} · due {timezone.localtime(sla.resolution_due_at):%d %b %H:%M}",
                    t,
                    sla.resolution_warn_at,
                    False,
                )
            elif sla and sla.resolution_status == MetricStatus.BREACHED:
                for user in {t.assigned_agent, *managers}:
                    add(
                        user,
                        NotificationType.SLA_BREACHED,
                        f"{t.reference} breached its resolution target",
                        t.title,
                        t,
                        sla.resolution_due_at,
                        now - sla.resolution_due_at > timedelta(days=1),
                    )
        return made
