"""Maintenance commands and scheduled-task wrappers (they run unattended against real data)."""

from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.ai.models import AIAnalysis
from apps.customers.models import Customer
from apps.organizations.catalog import RoleCode
from apps.sla.models import SLAInstance
from apps.tickets.models import Ticket

pytestmark = pytest.mark.django_db


def _ticket(org, n, **kw):
    customer, _ = Customer.objects.get_or_create(organization=org, name="Bank")
    return Ticket.objects.create(organization=org, number=n, title=f"T{n}", description="d", customer=customer, **kw)


def test_sla_backfill_starts_missing_clocks_only(org):
    open_t, closed_t = _ticket(org, 1), _ticket(org, 2, status="closed")
    out = StringIO()
    call_command("sla_backfill", org=org.slug, dry_run=True, stdout=out)
    assert "1 open ticket(s) would get an SLA clock" in out.getvalue() and not SLAInstance.objects.exists()
    call_command("sla_backfill", org=org.slug, stdout=out)
    assert list(SLAInstance.objects.values_list("ticket_id", flat=True)) == [open_t.id]
    assert not SLAInstance.objects.filter(ticket=closed_t).exists()
    call_command("sla_backfill", org=org.slug, stdout=out)  # idempotent
    assert SLAInstance.objects.count() == 1


def test_ai_backfill_triages_untriaged_tickets_and_requeues(org, make_member):
    make_member(org, RoleCode.ORG_ADMIN)
    _ticket(org, 1)
    _ticket(org, 2)
    out = StringIO()
    call_command("ai_backfill", org=org.slug, limit=10, insights=True, stdout=out)
    assert AIAnalysis.objects.filter(ticket__isnull=False).values("ticket").distinct().count() == 2
    triaged = AIAnalysis.objects.filter(ticket__isnull=False).count()
    call_command("ai_backfill", org=org.slug, limit=10, stdout=out)  # already triaged: nothing new
    assert AIAnalysis.objects.filter(ticket__isnull=False).count() == triaged
    call_command("ai_backfill", org=org.slug, requeue_pending=True, stdout=out)
    with pytest.raises(CommandError):
        call_command("ai_backfill", org="no-such-org", stdout=out)


def test_scheduled_task_wrappers_call_their_services():
    from apps.field_service.tasks import purge_old_locations
    from apps.integrations.tasks import poll_mailboxes, sweep_webhooks
    from apps.sla.tasks import scan

    with mock.patch("apps.sla.services.scan", return_value={"warning": 1}) as s:
        assert scan.run() == {"warning": 1} and s.called
    with mock.patch("apps.field_service.services.purge_old_locations", return_value=3):
        assert purge_old_locations.run() == 3
    with mock.patch("apps.integrations.services.sweep_due", return_value=2):
        assert sweep_webhooks.run() == 2
    assert poll_mailboxes.run() == {}  # no mailboxes configured


def test_mailbox_polling_skips_overlapping_runs():
    from django.core.cache import cache

    from apps.integrations.tasks import poll_mailboxes

    cache.add("integrations:poll_mailboxes", 1, timeout=60)
    assert poll_mailboxes.run() == {"skipped": "already running"}


def test_inbound_connector_connection_check(org, make_member, client_for):
    admin = make_member(org, RoleCode.ORG_ADMIN)
    client = client_for(admin)
    i = client.post(
        "/api/v1/integrations/", {"kind": "inbound", "provider": "generic", "name": "In"}, format="json"
    ).json()
    assert client.post(f"/api/v1/integrations/{i['id']}/test/").json()["ok"] is True
    admin.is_active = False
    admin.save()
    other = client_for(make_member(org, RoleCode.ORG_ADMIN))
    r = other.post(f"/api/v1/integrations/{i['id']}/test/").json()
    assert r["ok"] is False and "can no longer create tickets" in r["message"]
