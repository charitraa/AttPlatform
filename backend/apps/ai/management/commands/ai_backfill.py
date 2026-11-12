"""
Queue AI work for tickets that existed before AI was enabled.

    python manage.py ai_backfill --org acme [--limit 50] [--knowledge] [--insights]

* triage (classification, priority, routing) for open tickets with no analyses yet
* --knowledge: draft knowledge articles from closed tickets that have resolution notes
* --insights: one insights run
* --requeue-pending: re-queue analyses stuck in "pending" for over 5 minutes
  (e.g. after a worker outage dropped their messages)

Work is queued on the `ai` Celery queue, exactly like live triggers.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.ai.models import AIAnalysis
from apps.ai.services import TRIAGE_KINDS, request_insights, request_ticket_analysis
from apps.knowledge.models import KnowledgeArticle
from apps.organizations.models import Organization
from apps.tickets.models import ACTIVE_STATUSES, Ticket, TicketStatus


class Command(BaseCommand):
    help = "Queue AI triage / knowledge extraction / insights for existing data."

    def add_arguments(self, parser):
        parser.add_argument("--org", required=True, help="Organization slug")
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--knowledge", action="store_true")
        parser.add_argument("--insights", action="store_true")
        parser.add_argument("--requeue-pending", action="store_true")

    def handle(self, *args, org, limit, knowledge, insights, requeue_pending, **options):
        try:
            organization = Organization.objects.get(slug=org)
        except Organization.DoesNotExist as exc:
            raise CommandError(f"Organization '{org}' not found.") from exc

        if requeue_pending:
            from datetime import timedelta

            from django.utils import timezone

            from apps.ai.tasks import run_analysis

            stuck = AIAnalysis.objects.filter(
                organization=organization,
                status=AIAnalysis.Status.PENDING,
                created_at__lt=timezone.now() - timedelta(minutes=5),
            )
            ids = [str(i) for i in stuck.values_list("id", flat=True)[: limit * 10]]
            for analysis_id in ids:
                run_analysis.delay(analysis_id)
            self.stdout.write(f"Re-queued {len(ids)} stuck analysis(es).")
            return

        analysed = AIAnalysis.objects.filter(organization=organization, ticket__isnull=False).values("ticket_id")
        open_tickets = (
            Ticket.objects.filter(organization=organization, status__in=ACTIVE_STATUSES, archived_at__isnull=True)
            .exclude(id__in=analysed)
            .order_by("-created_at")[:limit]
        )
        queued = 0
        for ticket in open_tickets:
            request_ticket_analysis(ticket=ticket, kinds=list(TRIAGE_KINDS), trigger="backfill")
            queued += 1
        self.stdout.write(f"Queued triage for {queued} open ticket(s).")

        if knowledge:
            drafted = KnowledgeArticle.objects.filter(organization=organization).values("source_ticket_id")
            closed = (
                Ticket.objects.filter(organization=organization, status=TicketStatus.CLOSED)
                .exclude(resolution_notes="")
                .exclude(id__in=drafted)
                .order_by("-closed_at")[:limit]
            )
            n = 0
            for ticket in closed:
                request_ticket_analysis(ticket=ticket, kinds=["knowledge_extraction"], trigger="backfill")
                n += 1
            self.stdout.write(f"Queued knowledge extraction for {n} closed ticket(s).")

        if insights:
            request_insights(organization=organization, trigger="backfill")
            self.stdout.write("Queued one insights run.")
        self.stdout.write(self.style.SUCCESS("Done. Results appear as the `ai` worker processes the queue."))
