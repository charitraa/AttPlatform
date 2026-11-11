from datetime import timedelta

import pytest
from django.utils import timezone

from apps.customers.models import Customer, CustomerContact
from apps.organizations.catalog import RoleCode
from apps.tickets.models import Ticket

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(org, make_member):
    customer = Customer.objects.create(organization=org, name="Bank")
    agent = make_member(org, RoleCode.SUPPORT_AGENT)
    tech = make_member(org, RoleCode.FIELD_TECHNICIAN)
    now = timezone.now()

    def t(n, **kw):
        defaults = {"organization": org, "number": n, "title": f"T{n}", "description": "d", "customer": customer}
        return Ticket.objects.create(**{**defaults, **kw})

    t(1, status="new", priority="critical")
    t(2, status="in_progress", assigned_agent=agent.user, due_at=now - timedelta(hours=1))  # overdue
    t(3, status="resolved", assigned_agent=agent.user, resolved_at=now)
    t(4, status="closed", resolved_at=now - timedelta(days=1), closed_at=now)
    t(5, status="in_progress", assigned_technician=tech.user, priority="critical")
    t(6, status="new", archived_at=now)  # archived: excluded
    # Make resolution times deterministic: created 10h / 20h before resolution.
    Ticket.objects.filter(number=3).update(created_at=now - timedelta(hours=10))
    Ticket.objects.filter(number=4).update(created_at=now - timedelta(days=1, hours=20))
    return {"agent": agent, "tech": tech, "customer": customer}


def test_summary_counts_from_real_data(client_for, admin, setup):
    body = client_for(admin).get("/api/v1/dashboard/summary/").json()
    assert body["total"] == 5
    assert body["open"] == 3
    assert body["in_progress"] == 2
    assert body["resolved"] == 1 and body["closed"] == 1
    assert body["overdue"] == 1
    assert body["critical_open"] == 2
    assert body["unassigned_open"] == 2
    assert body["avg_resolution_hours"] == 15.0
    # Metrics from modules that don't exist yet are null with a reason — never invented.
    assert body["sla_compliance"] is None and "Phase 6" in body["unavailable"]["sla_compliance"]
    assert body["technicians_available"] is None


def test_summary_respects_row_level_visibility(client_for, setup):
    body = client_for(setup["tech"]).get("/api/v1/dashboard/summary/").json()
    assert body["total"] == 1 and body["critical_open"] == 1


def test_trends_returns_one_row_per_day_in_org_timezone(client_for, admin, setup):
    days = client_for(admin).get("/api/v1/dashboard/trends/", {"days": 7}).json()["days"]
    assert len(days) == 7
    assert sum(d["created"] for d in days) >= 4
    assert days[-1]["resolved"] >= 1


def test_days_parameter_is_clamped_and_validated(client_for, admin, setup):
    client = client_for(admin)
    assert len(client.get("/api/v1/dashboard/trends/", {"days": 9999}).json()["days"]) == 180
    assert client.get("/api/v1/dashboard/trends/", {"days": "abc"}).status_code == 400


def test_breakdown_and_workload(client_for, admin, setup):
    client = client_for(admin)
    breakdown = client.get("/api/v1/dashboard/breakdown/").json()
    assert {p["priority"]: p["count"] for p in breakdown["priority"]}["critical"] == 2
    agents = client.get("/api/v1/dashboard/workload/").json()["agents"]
    assert agents[0]["open"] == 1 and agents[0]["resolved"] == 1


def test_workload_requires_view_all(client_for, setup):
    assert client_for(setup["tech"]).get("/api/v1/dashboard/workload/").status_code == 403


def test_activity_hides_internal_events_from_customers(client_for, org, make_member, setup, admin):
    portal = make_member(org, RoleCode.CUSTOMER)
    CustomerContact.objects.create(customer=setup["customer"], user=portal.user, name="IT")
    ticket = Ticket.objects.get(number=1)
    staff = client_for(admin)
    staff.post(f"/api/v1/tickets/{ticket.id}/comments/", {"body": "secret", "visibility": "internal"}, format="json")
    staff.post(f"/api/v1/tickets/{ticket.id}/comments/", {"body": "hello"}, format="json")
    staff_events = client_for(admin).get("/api/v1/dashboard/activity/").json()["events"]
    portal_events = client_for(portal).get("/api/v1/dashboard/activity/").json()["events"]
    assert len(staff_events) == 2 and len(portal_events) == 1
