from datetime import date, datetime, timedelta

import pytest
from django.utils import timezone

from apps.customers.models import Customer
from apps.organizations.catalog import RoleCode
from apps.sla import services
from apps.sla.models import BusinessHours, Holiday, SLAEvent, SLAInstance, SLAPolicy, SLATarget
from apps.tickets.models import Ticket, TicketCategory, TicketHistory

pytestmark = pytest.mark.django_db
H = 3600


@pytest.fixture
def setup(org, make_member):
    customer = Customer.objects.create(organization=org, name="Himalayan Bank", tier="standard")
    gold = Customer.objects.create(organization=org, name="Everest Hotel", tier="enterprise")
    return {
        "customer": customer,
        "gold": gold,
        "agent": make_member(org, RoleCode.SUPPORT_AGENT, email="agent@acme.test"),
        "ops": make_member(org, RoleCode.OPS_MANAGER, email="ops@acme.test"),
    }


def always(org):
    """Make the default policy run 24/7 so expectations are plain arithmetic."""
    policy = SLAPolicy.objects.get(organization=org, is_default=True)
    policy.business_hours = None
    policy.save()
    return policy


def create(client_for, setup, customer=None, **extra):
    r = client_for(setup["agent"]).post(
        "/api/v1/tickets/",
        {
            "title": "AC down",
            "description": "Hot",
            "customer": str((customer or setup["customer"]).id),
            "priority": "high",
            **extra,
        },
        format="json",
    )
    assert r.status_code == 201, r.json()
    return Ticket.objects.get(pk=r.json()["id"])


def set_status(ticket, status, at):
    Ticket.objects.filter(pk=ticket.pk).update(status=status)
    return services.sync_ticket(ticket.pk, now=at)


# ------------------------------------------------------------------ defaults
def test_new_organizations_get_working_hours_and_a_complete_default_policy(org):
    policy = SLAPolicy.objects.get(organization=org, is_default=True)
    assert policy.business_hours.name == "Standard hours"
    assert set(policy.targets.values_list("priority", flat=True)) == {"low", "medium", "high", "critical"}


# --------------------------------------------------------------------- clock
def test_creating_a_ticket_starts_the_clock_and_sets_due_at(client_for, setup, org):
    always(org)
    ticket = create(client_for, setup)
    sla = ticket.sla
    assert (sla.policy_name, sla.priority, sla.response_minutes, sla.resolution_minutes) == (
        "Standard",
        "high",
        60,
        480,
    )
    assert sla.response_due_at == sla.started_at + timedelta(hours=1)
    assert sla.resolution_due_at == sla.started_at + timedelta(hours=8)
    assert sla.resolution_warn_at == sla.started_at + timedelta(hours=8 * 0.8)
    ticket.refresh_from_db()
    assert ticket.due_at == sla.resolution_due_at
    assert SLAEvent.objects.filter(sla=sla, type="applied").count() == 1


def test_working_hours_and_holidays_shape_the_deadline(client_for, setup, org):
    hours = BusinessHours.objects.get(organization=org)
    hours.timezone = "Asia/Kathmandu"
    hours.save()
    Holiday.objects.create(business_hours=hours, date=date(2026, 11, 16), name="Festival")  # a Monday
    ticket = create(client_for, setup, priority="critical")  # 30 min response, 4 h resolution
    sla = ticket.sla
    tz = timezone.get_fixed_timezone(345)
    sla.started_at = datetime(2026, 11, 13, 15, 0, tzinfo=tz)  # Friday 15:00 local
    services._compute(sla, services.calendar_for(hours))
    # 2h left on Friday, Saturday off, Sunday is a working day in Nepal → Sunday 11:00; Monday's holiday not needed
    assert sla.resolution_due_at == datetime(2026, 11, 15, 11, 0, tzinfo=tz)
    # Response: Friday 15:30
    assert sla.response_due_at == datetime(2026, 11, 13, 15, 30, tzinfo=tz)


def test_waiting_on_the_customer_pauses_only_the_resolution_clock(client_for, setup, org):
    always(org)
    ticket = create(client_for, setup)
    start = ticket.sla.started_at
    sla = set_status(ticket, "pending_customer", start + timedelta(hours=1))
    assert sla.is_paused
    ticket.refresh_from_db()
    assert ticket.due_at is None  # no running deadline while paused
    sla = set_status(ticket, "in_progress", start + timedelta(hours=3))
    assert not sla.is_paused and sla.paused_seconds == 2 * H
    assert sla.resolution_due_at == start + timedelta(hours=10)  # 8 h target + 2 h paused
    assert sla.response_due_at == start + timedelta(hours=1)  # unchanged
    assert list(sla.events.values_list("type", flat=True)) == ["applied", "paused", "resumed"]


def test_a_customer_reply_resumes_the_clock_without_a_status_event(client_for, setup, org, make_member):
    always(org)
    ticket = create(client_for, setup)
    client_for(setup["agent"]).post(
        f"/api/v1/tickets/{ticket.id}/transition/", {"status": "pending_customer"}, format="json"
    )
    assert SLAInstance.objects.get(ticket=ticket).is_paused
    portal = make_member(org, RoleCode.CUSTOMER, email="cust@bank.test")
    setup["customer"].contacts.create(name="Cust", email="cust@bank.test", user=portal.user)
    r = client_for(portal).post(f"/api/v1/tickets/{ticket.id}/comments/", {"body": "Still broken"}, format="json")
    assert r.status_code == 201, r.json()
    assert not SLAInstance.objects.get(ticket=ticket).is_paused


def test_first_public_staff_reply_meets_the_response_target(client_for, setup, org):
    always(org)
    ticket = create(client_for, setup)
    client = client_for(setup["agent"])
    client.post(f"/api/v1/tickets/{ticket.id}/comments/", {"body": "Checking", "visibility": "internal"}, format="json")
    assert SLAInstance.objects.get(ticket=ticket).response_status == "on_track"  # internal notes don't count
    client.post(f"/api/v1/tickets/{ticket.id}/comments/", {"body": "On it", "visibility": "public"}, format="json")
    sla = SLAInstance.objects.get(ticket=ticket)
    assert sla.response_status == "met" and sla.responded_at is not None


def test_resolving_meets_the_target_and_reopening_resumes(client_for, setup, org):
    always(org)
    ticket = create(client_for, setup)
    start = ticket.sla.started_at
    Ticket.objects.filter(pk=ticket.pk).update(resolved_at=start + timedelta(hours=2))
    sla = set_status(ticket, "resolved", start + timedelta(hours=2))
    assert sla.resolution_status == "met" and sla.response_status == "met"  # resolution counts as a response
    ticket.refresh_from_db()
    assert ticket.due_at is None
    sla = set_status(ticket, "reopened", start + timedelta(hours=5))
    assert sla.resolution_status == "on_track" and sla.resolved_at is None
    assert sla.resolution_due_at == start + timedelta(hours=11)  # 3 h between resolve and reopen don't count


def test_changing_priority_takes_the_new_target(client_for, setup, org):
    always(org)
    ticket = create(client_for, setup)
    r = client_for(setup["agent"]).patch(f"/api/v1/tickets/{ticket.id}/", {"priority": "critical"}, format="json")
    assert r.status_code == 200, r.json()
    sla = SLAInstance.objects.get(ticket=ticket)
    assert (sla.priority, sla.response_minutes, sla.resolution_minutes) == ("critical", 30, 240)
    assert sla.resolution_due_at == sla.started_at + timedelta(hours=4)
    assert sla.events.filter(type="recalculated").exists()


def test_policy_edits_do_not_rewrite_running_clocks(client_for, setup, org):
    policy = always(org)
    ticket = create(client_for, setup)
    SLATarget.objects.filter(policy=policy, priority="high").update(resolution_minutes=60)
    services.sync_ticket(ticket.pk)
    assert SLAInstance.objects.get(ticket=ticket).resolution_minutes == 480


# ------------------------------------------------------------------ matching
def test_most_specific_policy_wins_and_falls_back_without_a_target(client_for, setup, org):
    always(org)
    vip = SLAPolicy.objects.create(
        organization=org, name="Enterprise", conditions={"customer_tiers": ["enterprise"]}, priority_order=10
    )
    SLATarget.objects.create(policy=vip, priority="high", first_response_minutes=15, resolution_minutes=120)
    assert create(client_for, setup, customer=setup["gold"]).sla.policy_name == "Enterprise"
    assert create(client_for, setup).sla.policy_name == "Standard"
    # The VIP policy has no "low" target, so low-priority VIP tickets use the default.
    assert create(client_for, setup, customer=setup["gold"], priority="low").sla.policy_name == "Standard"


def test_category_and_channel_conditions(client_for, setup, org):
    always(org)
    hvac = TicketCategory.objects.create(organization=org, name="HVAC")
    p = SLAPolicy.objects.create(
        organization=org,
        name="HVAC phone",
        conditions={"categories": [str(hvac.id)], "channels": ["phone"]},
        priority_order=5,
    )
    SLATarget.objects.create(policy=p, priority="high", first_response_minutes=10, resolution_minutes=60)
    assert create(client_for, setup, category=str(hvac.id), channel="phone").sla.policy_name == "HVAC phone"
    assert create(client_for, setup, category=str(hvac.id), channel="email").sla.policy_name == "Standard"


def test_inactive_policies_are_ignored(client_for, setup, org):
    always(org)
    p = SLAPolicy.objects.create(organization=org, name="Paused", priority_order=1, is_active=False)
    SLATarget.objects.create(policy=p, priority="high", first_response_minutes=1, resolution_minutes=2)
    assert create(client_for, setup).sla.policy_name == "Standard"


# ------------------------------------------------------------------- monitor
def test_monitor_warns_then_breaches_once_and_escalates(client_for, setup, org, django_capture_on_commit_callbacks):
    always(org)
    ticket = create(client_for, setup)
    client_for(setup["agent"]).post(
        f"/api/v1/tickets/{ticket.id}/comments/", {"body": "Hi", "visibility": "public"}, format="json"
    )
    start = SLAInstance.objects.get(ticket=ticket).started_at

    assert services.scan(now=start + timedelta(hours=6))["warning"] == 0  # 75 % of 8 h
    assert services.scan(now=start + timedelta(hours=7))["warning"] == 1  # past 80 %
    assert services.scan(now=start + timedelta(hours=7, minutes=30))["warning"] == 0  # once only

    counts = services.scan(now=start + timedelta(hours=8, minutes=1))
    assert counts == {"warning": 0, "breached": 1, "escalated": 1}
    assert services.scan(now=start + timedelta(hours=9)) == {"warning": 0, "breached": 0, "escalated": 0}

    sla = SLAInstance.objects.get(ticket=ticket)
    assert sla.resolution_status == "breached" and sla.response_status == "met" and sla.escalated_at
    ticket.refresh_from_db()
    assert ticket.status == "escalated"
    hist = TicketHistory.objects.filter(ticket=ticket, field="status", new_value="escalated").get()
    assert hist.actor is None and hist.actor_type == "system"
    assert list(sla.events.filter(type__in=["warning", "breached", "escalated"]).values_list("type", "metric")) == [
        ("warning", "resolution"),
        ("breached", "resolution"),
        ("escalated", "resolution"),
    ]


def test_response_breach_is_tracked_separately_and_skips_straight_to_breached(client_for, setup, org):
    always(org)
    ticket = create(client_for, setup)
    start = ticket.sla.started_at
    assert services.scan(now=start + timedelta(hours=2)) == {"warning": 0, "breached": 1, "escalated": 0}
    sla = SLAInstance.objects.get(ticket=ticket)
    assert sla.response_status == "breached" and sla.resolution_status == "on_track"
    assert not sla.events.filter(type="warning", metric="response").exists()  # already past due: no late warning


def test_paused_clocks_are_not_breached_and_breach_is_final(client_for, setup, org):
    policy = always(org)
    policy.escalate_on_breach = False
    policy.save()
    ticket = create(client_for, setup)
    start = ticket.sla.started_at
    set_status(ticket, "pending_parts", start + timedelta(minutes=30))
    assert services.scan(now=start + timedelta(hours=20))["breached"] == 1  # only the response target
    assert SLAInstance.objects.get(ticket=ticket).resolution_status == "on_track"

    set_status(ticket, "in_progress", start + timedelta(hours=20))
    services.scan(now=start + timedelta(hours=28))
    ticket.refresh_from_db()
    assert ticket.status == "in_progress"  # escalate_on_breach is off
    sla = set_status(ticket, "resolved", start + timedelta(hours=29))
    assert sla.resolution_status == "breached" and sla.resolved_at  # resolving late doesn't turn it into "met"


def test_compliance_report_and_dashboard(client_for, setup, org):
    always(org)
    on_time, late = create(client_for, setup), create(client_for, setup)
    set_status(on_time, "resolved", on_time.sla.started_at + timedelta(hours=1))
    services.scan(now=late.sla.started_at + timedelta(hours=9))
    report = client_for(setup["ops"]).get("/api/v1/sla/report/").json()
    assert report["by_priority"]["high"]["resolution_met"] == 1
    assert report["by_priority"]["high"]["resolution_breached"] == 1
    assert report["resolution_compliance"] == 0.5
    assert client_for(setup["ops"]).get("/api/v1/dashboard/summary/").json()["sla_compliance"] == 0.5


# ----------------------------------------------------------------------- API
def test_ticket_sla_endpoint_and_list_summary(client_for, setup, org, other_org, make_member):
    always(org)
    ticket = create(client_for, setup)
    body = client_for(setup["agent"]).get(f"/api/v1/tickets/{ticket.id}/sla/").json()
    assert body["policy_name"] == "Standard" and body["paused"] is False
    assert 8 * H - 60 < body["resolution_remaining_seconds"] <= 8 * H
    assert [e["type"] for e in body["events"]] == ["applied"]
    listed = client_for(setup["agent"]).get("/api/v1/tickets/").json()["results"][0]
    assert listed["sla"]["resolution_status"] == "on_track"

    outsider = make_member(other_org, RoleCode.ORG_ADMIN)
    assert client_for(outsider).get(f"/api/v1/tickets/{ticket.id}/sla/").status_code == 404
    portal = make_member(org, RoleCode.CUSTOMER)
    assert client_for(portal).get(f"/api/v1/tickets/{ticket.id}/sla/").status_code == 403


def test_policy_api_permissions_and_validation(client_for, setup, org, other_org):
    agent, ops = client_for(setup["agent"]), client_for(setup["ops"])
    assert agent.get("/api/v1/sla/policies/").status_code == 200
    body = {
        "name": "VIP",
        "targets": [{"priority": "high", "first_response_minutes": 15, "resolution_minutes": 120}],
        "conditions": {"customer_tiers": ["enterprise"]},
        "priority_order": 10,
    }
    assert agent.post("/api/v1/sla/policies/", body, format="json").status_code == 403

    foreign = TicketCategory.objects.create(organization=other_org, name="Theirs")
    bad = ops.post("/api/v1/sla/policies/", {**body, "conditions": {"categories": [str(foreign.id)]}}, format="json")
    assert bad.status_code == 400 and "categories" in str(bad.json())
    slow = {**body, "targets": [{"priority": "high", "first_response_minutes": 200, "resolution_minutes": 100}]}
    assert ops.post("/api/v1/sla/policies/", slow, format="json").status_code == 400

    created = ops.post("/api/v1/sla/policies/", body, format="json")
    assert created.status_code == 201, created.json()
    # A non-default policy may cover some priorities; the default must cover all of them.
    as_default = ops.patch(f"/api/v1/sla/policies/{created.json()['id']}/", {"is_default": True}, format="json")
    assert as_default.status_code == 400 and "every priority" in str(as_default.json())

    default = SLAPolicy.objects.get(organization=org, is_default=True)
    assert ops.delete(f"/api/v1/sla/policies/{default.id}/").status_code == 409
    assert ops.delete(f"/api/v1/sla/policies/{created.json()['id']}/").status_code == 204


def test_switching_the_default_policy(client_for, setup, org):
    ops = client_for(setup["ops"])
    targets = [
        {"priority": p, "first_response_minutes": 10, "resolution_minutes": 100}
        for p in ("low", "medium", "high", "critical")
    ]
    r = ops.post("/api/v1/sla/policies/", {"name": "Strict", "is_default": True, "targets": targets}, format="json")
    assert r.status_code == 201, r.json()
    assert list(SLAPolicy.objects.filter(organization=org, is_default=True).values_list("name", flat=True)) == [
        "Strict"
    ]


def test_business_hours_api(client_for, setup, org):
    ops = client_for(setup["ops"])
    bad = ops.post(
        "/api/v1/sla/business-hours/",
        {"name": "Night", "timezone": "Mars/Base", "schedule": {"mon": [["22:00", "06:00"]]}},
        format="json",
    )
    assert bad.status_code == 400 and {"timezone", "schedule"} <= set(bad.json()["error"]["details"])
    ok = ops.post(
        "/api/v1/sla/business-hours/",
        {
            "name": "Night",
            "timezone": "Asia/Kathmandu",
            "schedule": {"mon": [["22:00", "24:00"]]},
            "holidays": [{"date": "2026-12-25", "name": "Closed"}],
        },
        format="json",
    )
    assert ok.status_code == 201, ok.json()
    assert ok.json()["schedule"]["mon"] == [["22:00", "24:00"]] and ok.json()["schedule"]["tue"] == []
    used = BusinessHours.objects.get(organization=org, name="Standard hours")
    assert ops.delete(f"/api/v1/sla/business-hours/{used.id}/").status_code == 409  # the default policy uses it
