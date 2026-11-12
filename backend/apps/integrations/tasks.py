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
