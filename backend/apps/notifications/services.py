"""
Notification fan-out.

`notify` creates one notification per recipient who (a) is an active member of the
organization and (b) has at least one channel enabled for the type. The in-app
copy is pushed over the WebSocket and each email is delivered by a retried Celery
task, both after the transaction commits.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from django.db import transaction
from django.utils import timezone

from apps.organizations.models import Membership

from . import realtime
from .models import DEFAULT_ENABLED, Channel, Notification, NotificationDelivery, NotificationPreference

PHONE_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def e164(phone: str) -> str | None:
    """'+977 984-720 6256' → '+9779847206256'; None unless it's a full international number."""
    compact = re.sub(r"[\s()\-.]", "", phone or "")
    return compact if PHONE_RE.match(compact) else None


def whatsapp_integration(organization):
    """The organization's WhatsApp integration that can send notifications, if any."""
    from apps.integrations.models import Integration

    for i in Integration.objects.filter(organization=organization, kind=Integration.Kind.WHATSAPP, is_enabled=True):
        if i.config.get("notification_template"):
            return i
    return None


def channels_for(organization) -> list[str]:
    return [Channel.IN_APP, Channel.EMAIL] + ([Channel.WHATSAPP] if whatsapp_integration(organization) else [])


def preferences_for(user, organization) -> dict[str, dict[str, bool]]:
    prefs = {t: {**dict(channels), Channel.WHATSAPP: False} for t, channels in DEFAULT_ENABLED.items()}
    for p in NotificationPreference.objects.filter(user=user, organization=organization):
        if p.type in prefs:
            prefs[p.type][p.channel] = p.enabled
    return prefs


@transaction.atomic
def set_preferences(user, organization, items: Iterable[dict]) -> dict[str, dict[str, bool]]:
    for item in items:
        NotificationPreference.objects.update_or_create(
            user=user,
            organization=organization,
            type=item["type"],
            channel=item["channel"],
            defaults={"enabled": item["enabled"]},
        )
    return preferences_for(user, organization)


def members_with_permission(organization, permission: str):
    """Active members whose role grants `permission` (users)."""
    return [
        m.user
        for m in Membership.objects.filter(
            organization=organization, is_active=True, role__permissions__code=permission, user__is_active=True
        )
        .select_related("user")
        .distinct()
    ]


def notify(
    *,
    organization,
    recipients: Iterable,
    type: str,
    title: str,
    body: str = "",
    link: str = "",
    data: dict | None = None,
    exclude_user_id=None,
) -> list[Notification]:
    unique = {u.pk: u for u in recipients if u is not None and str(u.pk) != str(exclude_user_id or "")}
    if not unique:
        return []
    active_ids = set(
        Membership.objects.filter(
            organization=organization, user_id__in=unique, is_active=True, user__is_active=True
        ).values_list("user_id", flat=True)
    )
    created = []
    wa = whatsapp_integration(organization)
    with transaction.atomic():
        for user_id in active_ids:
            user = unique[user_id]
            channels = preferences_for(user, organization).get(type, {})
            if not wa or not e164(user.phone):
                channels = {**channels, Channel.WHATSAPP: False}
            if not any(channels.values()):
                continue
            n = Notification.objects.create(
                organization=organization,
                recipient=user,
                type=type,
                title=title[:200],
                body=body,
                link=link,
                data=data or {},
                in_app=channels.get(Channel.IN_APP, False),
            )
            created.append(n)
            if channels.get(Channel.EMAIL) and user.email:
                delivery = NotificationDelivery.objects.create(notification=n, channel=Channel.EMAIL)
                transaction.on_commit(lambda d=delivery.pk: _queue_email(d))
            if wa and channels.get(Channel.WHATSAPP) and e164(user.phone):
                delivery = NotificationDelivery.objects.create(notification=n, channel=Channel.WHATSAPP)
                transaction.on_commit(lambda d=delivery.pk: _queue_whatsapp(d))
            if n.in_app:
                transaction.on_commit(
                    lambda n=n: realtime.push(
                        realtime.user_group(n.recipient_id, n.organization_id),
                        "notification.created",
                        id=str(n.id),
                        kind=n.type,
                        title=n.title,
                        link=n.link,
                    )
                )
    return created


def _queue_email(delivery_id) -> None:
    from .tasks import deliver_email

    deliver_email.delay(str(delivery_id))


def _queue_whatsapp(delivery_id) -> None:
    from .tasks import deliver_whatsapp

    deliver_whatsapp.delay(str(delivery_id))


def inbox(user, organization):
    return Notification.objects.filter(recipient=user, organization=organization, in_app=True)


def mark_read(user, organization, ids=None) -> int:
    qs = inbox(user, organization).filter(read_at__isnull=True)
    if ids is not None:
        qs = qs.filter(id__in=ids)
    count = qs.update(read_at=timezone.now(), updated_at=timezone.now())
    if count:
        transaction.on_commit(lambda: realtime.push(realtime.user_group(user.pk, organization.pk), "notification.read"))
    return count
