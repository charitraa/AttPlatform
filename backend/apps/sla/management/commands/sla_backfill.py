"""
Start SLA clocks for open tickets created before SLA existed (or before a policy matched),
then run the monitor once so overdue tickets are flagged immediately.

    python manage.py sla_backfill [--org <slug>] [--dry-run]

Clocks start at the ticket's creation time, so old tickets may come out breached.
"""

from django.core.management.base import BaseCommand

from apps.organizations.models import Organization
from apps.sla import services
from apps.sla.services import STOPPED_STATUSES
from apps.tickets.models import Ticket


class Command(BaseCommand):
    help = "Apply SLA policies to open tickets without an SLA clock."

    def add_arguments(self, parser):
        parser.add_argument("--org", help="Organization slug (default: all).")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, org=None, dry_run=False, **options):
        orgs = Organization.objects.filter(slug=org) if org else Organization.objects.all()
        for o in orgs:
            services.ensure_default_policy(o)
        tickets = Ticket.objects.filter(organization__in=orgs, sla__isnull=True, archived_at__isnull=True).exclude(
            status__in=STOPPED_STATUSES
        )
        count = tickets.count()
        if dry_run:
            self.stdout.write(f"{count} open ticket(s) would get an SLA clock.")
            return
        applied = sum(1 for pk in tickets.values_list("pk", flat=True) if services.sync_ticket(pk))
        result = services.scan()
        self.stdout.write(
            self.style.SUCCESS(
                f"Started {applied} of {count} SLA clock(s). Monitor: {result['warning']} warning(s), "
                f"{result['breached']} breach(es), {result['escalated']} escalation(s)."
            )
        )
