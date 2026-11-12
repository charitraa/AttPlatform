from celery import shared_task


@shared_task(name="integrations.deliver_webhook", queue="webhooks", acks_late=True)
def deliver_webhook(delivery_id: str) -> str:
    """One attempt; the service schedules the next one (fixed backoff schedule) when needed."""
    from .services import deliver

    return deliver(delivery_id)


@shared_task(name="integrations.sweep_webhooks", queue="webhooks")
def sweep_webhooks() -> int:
    """Every 5 minutes (beat): re-queue retries whose task was lost."""
    from .services import sweep_due

    return sweep_due()


@shared_task(name="integrations.process_inbound", queue="webhooks", acks_late=True)
def process_inbound(event_id: str) -> str:
    from .services import process_inbound as run

    return run(event_id)


@shared_task(name="integrations.poll_mailboxes", queue="webhooks")
def poll_mailboxes() -> dict:
    """Every 2 minutes (beat): check each enabled email-to-ticket mailbox. Overlapping runs are skipped."""
    from django.core.cache import cache

    from .models import Integration
    from .services import poll_mailbox

    if not cache.add("integrations:poll_mailboxes", 1, timeout=110):
        return {"skipped": "already running"}
    try:
        return {
            str(i.pk): poll_mailbox(i) for i in Integration.objects.filter(kind=Integration.Kind.EMAIL, is_enabled=True)
        }
    finally:
        cache.delete("integrations:poll_mailboxes")
