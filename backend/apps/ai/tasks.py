import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="ai.run_analysis", queue="ai", acks_late=True)
def run_analysis(analysis_id: str) -> str:
    """Retries live inside apps.ai.client (per provider error type), not at the Celery level."""
    from .models import AIAnalysis
    from .services import execute

    analysis = AIAnalysis.objects.select_related("organization", "ticket").filter(pk=analysis_id).first()
    if analysis is None:
        return "missing"
    return execute(analysis).status


@shared_task(name="ai.generate_daily_insights", queue="ai")
def generate_daily_insights() -> int:
    """Beat task: one insights run per active organization with AI enabled."""
    from apps.organizations.models import Organization

    from .services import ai_enabled, request_insights

    count = 0
    for org in Organization.objects.filter(is_active=True):
        if ai_enabled(org):
            request_insights(organization=org, trigger="schedule")
            count += 1
    return count


@shared_task(name="ai.autopilot", queue="ai", acks_late=True)
def autopilot(ticket_id: str) -> dict:
    """Run the AI autopilot for a new ticket (see services.run_autopilot)."""
    from apps.tickets.models import Ticket

    from .services import run_autopilot

    ticket = Ticket.objects.select_related("organization").filter(pk=ticket_id).first()
    return run_autopilot(ticket) if ticket else {}
