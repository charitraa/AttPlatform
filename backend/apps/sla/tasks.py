from celery import shared_task


@shared_task(name="sla.scan", queue="sla", acks_late=True, expires=55)
def scan() -> dict:
    """Every minute (beat): record warnings and breaches that have become due."""
    from .services import scan as run

    return run()
