from celery import shared_task
from django.utils import timezone


@shared_task(name="core.ping")
def ping() -> dict:
    """Round-trip check that a worker is consuming the queue."""
    return {"pong": True, "at": timezone.now().isoformat()}
