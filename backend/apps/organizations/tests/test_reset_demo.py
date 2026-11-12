from datetime import timedelta

import pytest
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from apps.notifications.models import NotificationDelivery
from apps.portal.models import CustomerFeedback
from apps.sla.models import MetricStatus, SLAInstance
from apps.sla.services import compliance
from apps.tickets.models import Ticket

pytestmark = pytest.mark.django_db


def test_reset_demo_builds_realistic_recent_data_quietly(django_capture_on_commit_callbacks):
    call_command("seed_demo", password="Demo!Pass2026")
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        call_command("reset_demo", count=40, seed=3)
        call_command("reset_demo", count=40, seed=3)  # repeatable
    assert callbacks == []  # events muted: no notifications, webhooks or AI
    assert mail.outbox == [] and not NotificationDelivery.objects.exists()

    now = timezone.now()
    tickets = Ticket.objects.filter(organization__slug="acme")
    assert tickets.count() == 40 and tickets.order_by("number").first().number == 1  # numbering restarted
    assert all(now - timedelta(days=31) < t.created_at <= now for t in tickets)
    assert SLAInstance.objects.filter(ticket__in=tickets).count() == 40
    for t in tickets.filter(resolved_at__isnull=False):
        assert t.created_at < t.resolved_at <= now
    report = compliance(tickets.first().organization, start=now - timedelta(days=31), end=now)
    assert 0.55 <= report["resolution_compliance"] <= 0.97  # realistic, not 0 % and not perfect
    statuses = set(SLAInstance.objects.values_list("resolution_status", flat=True))
    assert {MetricStatus.MET, MetricStatus.BREACHED} <= statuses
    assert CustomerFeedback.objects.exists()
