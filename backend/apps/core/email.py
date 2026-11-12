"""Transactional email. Sending happens in a Celery task after the DB commit."""

from django.db import transaction


def queue_email(*, to: str, subject: str, body: str) -> None:
    from .tasks import send_email

    transaction.on_commit(lambda: send_email.delay(to=to, subject=subject, body=body))
