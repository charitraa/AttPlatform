import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


@shared_task(
    name="notifications.deliver_email", bind=True, queue="notifications", acks_late=True, max_retries=MAX_ATTEMPTS
)
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
            EmailMessage(
                f"[{n.organization.name}] {n.title}",
                body,
                settings.DEFAULT_FROM_EMAIL,
                [n.recipient.email],
                # Marks the mail as automatic so mailboxes (and our own email-to-ticket) never act on it.
                headers={"Auto-Submitted": "auto-generated", "X-ATT-Notification": n.type},
            ).send()
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


@shared_task(
    name="notifications.deliver_message", bind=True, queue="notifications", acks_late=True, max_retries=MAX_ATTEMPTS
)
def deliver_message(self, delivery_id: str) -> str:
    """
    Send one WhatsApp / SMS / Telegram notification through the organization's integration.
    Never sends twice; provider errors that retrying can't fix fail at once.
    """
    from apps.integrations.connectors.base import ConnectorError, OutboundMessage
    from apps.integrations.services import send_message

    from .models import Channel, NotificationDelivery
    from .services import address_for, channel_integration

    error = None
    with transaction.atomic():
        d = (
            NotificationDelivery.objects.select_for_update(of=("self",))
            .select_related("notification__recipient", "notification__organization")
            .filter(pk=delivery_id)
            .first()
        )
        if d is None or d.status != NotificationDelivery.Status.PENDING:
            return "skipped"
        n, org = d.notification, d.notification.organization
        integration, to = channel_integration(org, d.channel), address_for(n.recipient, org, d.channel)
        d.attempts += 1
        if integration is None or to is None:  # set-up changed since queuing: nothing to retry
            d.status, d.last_error = NotificationDelivery.Status.FAILED, f"{d.channel} isn't set up for this person."
            d.save(update_fields=["attempts", "status", "last_error", "updated_at"])
            return "failed"
        link = f"{settings.FRONTEND_URL.rstrip('/')}{n.link}" if n.link else settings.FRONTEND_URL
        title = " ".join(n.title.split())[:200]  # template params can't contain new lines or runs of spaces
        if d.channel == Channel.WHATSAPP:
            message = OutboundMessage(
                to=to, template=integration.config["notification_template"], variables=[title, link]
            )
        else:
            message = OutboundMessage(to=to, text=f"{org.name}: {title}\n{link}")
        try:
            send_message(integration, message)
        except ConnectorError as exc:
            error = exc
            d.last_error = str(exc)[:500]
            permanent = any(m in str(exc) for m in ("(#131", "HTTP 400", "HTTP 401", "HTTP 403", "refused the request"))
            if d.attempts >= MAX_ATTEMPTS or permanent:
                d.status = NotificationDelivery.Status.FAILED
        else:
            d.status, d.sent_at, d.last_error = NotificationDelivery.Status.SENT, timezone.now(), ""
        d.save(update_fields=["attempts", "status", "sent_at", "last_error", "updated_at"])
    if error is None:
        return "sent"
    if d.status == NotificationDelivery.Status.FAILED:
        return "failed"
    raise self.retry(exc=error, countdown=min(600, 30 * 2 ** (d.attempts - 1)))


@shared_task(name="notifications.poll_telegram", queue="notifications")
def poll_telegram() -> dict:
    """Every minute (beat): pick up “/start <code>” messages that link people's Telegram chats."""
    from apps.integrations.models import Integration

    from .telegram import poll

    return {str(i.pk): poll(i) for i in Integration.objects.filter(kind=Integration.Kind.TELEGRAM, is_enabled=True)}
