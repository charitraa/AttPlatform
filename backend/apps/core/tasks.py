import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="core.ping")
def ping() -> dict:
    """Round-trip check that a worker is consuming the queue."""
    return {"pong": True, "at": timezone.now().isoformat()}


@shared_task(
    name="core.send_email",
    autoretry_for=(OSError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
    queue="notifications",
)
def send_email(*, to: str, subject: str, body: str) -> None:
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
    logger.info("Email sent: %s", subject)
