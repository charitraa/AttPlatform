"""
Quietly archive tickets created by browser tests (titles starting "[E2E"), plus any ticket numbers
given, and cancel their open work orders. No notifications, webhooks or AI run, and their SLA
clocks are removed, so they stop raising breach alerts.

    python manage.py archive_test_tickets --org acme [--numbers 48 49] [--dry-run]
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core import events
from apps.field_service.models import WorkOrder, WorkOrderStatus
from apps.organizations.models import Organization
from apps.sla.services import restamp
from apps.tickets.models import Ticket


class Command(BaseCommand):
    help = 'Archive "[E2E" test tickets (and --numbers) without notifying anyone; cancel their work orders.'

    def add_arguments(self, parser):
        parser.add_argument("--org", required=True, help="Organization slug")
        parser.add_argument("--numbers", nargs="*", type=int, default=[], help="Extra ticket numbers")
        parser.add_argument("--prefix", default="[E2E", help='Title prefix of test tickets (default "[E2E")')
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, org, numbers, prefix, dry_run, **options):
        organization = Organization.objects.filter(slug=org).first()
        if organization is None:
            raise CommandError(f"No organization {org!r}")
        tickets = list(
            Ticket.objects.filter(organization=organization, archived_at__isnull=True)
            .filter(Q(title__startswith=prefix) | Q(number__in=numbers))
            .order_by("number")
        )
        open_wos = WorkOrder.objects.filter(ticket__in=tickets).exclude(
            status__in=[WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED]
        )
        for t in tickets:
            self.stdout.write(f"{t.reference}  {t.title[:70]}")
        self.stdout.write(f"{len(tickets)} tickets, {open_wos.count()} open work orders")
        if dry_run or not tickets:
            return
        with events.muted(), transaction.atomic():
            wo_count = open_wos.update(status=WorkOrderStatus.CANCELLED, updated_at=timezone.now())
            Ticket.objects.filter(pk__in=[t.pk for t in tickets]).update(archived_at=timezone.now())
            for t in Ticket.objects.filter(pk__in=[t.pk for t in tickets]):
                restamp(t)  # archived → SLA clock removed
        self.stdout.write(self.style.SUCCESS(f"Archived {len(tickets)} tickets, cancelled {wo_count} work orders."))
