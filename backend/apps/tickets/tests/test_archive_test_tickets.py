import pytest
from django.core.management import call_command

from apps.customers.models import Customer
from apps.sla.models import SLAInstance
from apps.tickets.models import Ticket

pytestmark = pytest.mark.django_db


def test_archives_only_test_tickets_and_numbers(org):
    customer = Customer.objects.create(organization=org, name="C")
    make = lambda n, title: Ticket.objects.create(  # noqa: E731
        organization=org, number=n, title=title, description="d", customer=customer
    )
    e2e, extra, real = make(1, "[E2E abc] Printer"), make(2, "Live check"), make(3, "Real customer problem")
    call_command("archive_test_tickets", "--org", org.slug, "--numbers", "2")
    for t in (e2e, extra, real):
        t.refresh_from_db()
    assert e2e.archived_at and extra.archived_at and real.archived_at is None
    assert not SLAInstance.objects.filter(ticket__in=[e2e, extra]).exists()
