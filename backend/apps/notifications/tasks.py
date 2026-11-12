import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


@shared_task(name="notifications.deliver_email", bind=True, queue="notifications", acks_late=True, max_retries=MAX_ATTEMPTS)
def deliver_email(self, delivery_id: str) -> str:
    """Send one email delivery. Idempotent: a delivery already sent is never sent again."""
    from .models import NotificationDelivery

    # The row lock is held while sending so a redelivered task can't send the same email twice.
    error = None
    with transaction.atomic():
        d = (
            NotificationDelivery.objects.select_for_update()
            .select_related("notification__recipient", "notification__organization")
            .filter(pk=delivery_id)
            .first()
        )
        if d is None or d.status != NotificationDelivery.Status.PENDING:
            return "skipped"
        d.attempts += 1
        n = d.notification
        link = f"{settings.FRONTEND_URL.rstrip('/')}{n.link}" if n.link else settings.FRONTEND_URL
        body = (
            f"{n.body}\n\nOpen: {link}\n\n"
            f"— {n.organization.name} · You can change which emails you get under Notifications → Preferences."
        )
        try:
            send_mail(f"[{n.organization.name}] {n.title}", body, settings.DEFAULT_FROM_EMAIL, [n.recipient.email])
        except Exception as exc:  # noqa: BLE001 - recorded, then retried with backoff
            error = exc
            d.last_error = str(exc)[:500]
            if d.attempts >= MAX_ATTEMPTS:
                d.status = NotificationDelivery.Status.FAILED
        else:
            d.status, d.sent_at, d.last_error = NotificationDelivery.Status.SENT, timezone.now(), ""
        d.save(update_fields=["attempts", "status", "sent_at", "last_error", "updated_at"])
    # Retry only after the attempt has been committed.
    if error is None:
        return "sent"
    if d.status == NotificationDelivery.Status.FAILED:
        logger.error("Email delivery %s failed permanently: %s", delivery_id, error)
        return "failed"
    raise self.retry(exc=error, countdown=min(600, 30 * 2 ** (d.attempts - 1)))
