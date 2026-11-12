import json
from datetime import timedelta
from unittest import mock

import pytest
from django.core import mail

from apps.customers.models import Customer
from apps.field_service.models import Technician
from apps.notifications import services
from apps.notifications.models import Notification, NotificationDelivery
from apps.notifications.tasks import deliver_email
from apps.organizations.catalog import RoleCode
from apps.sla import services as sla_services
from apps.sla.models import SLAInstance, SLAPolicy
from apps.tickets.models import Ticket

pytestmark = pytest.mark.django_db


@pytest.fixture
def team(org, make_member):
    customer = Customer.objects.create(organization=org, name="Himalayan Bank")
    return {
        "customer": customer,
        "agent": make_member(org, RoleCode.SUPPORT_AGENT, email="agent@acme.test"),
        "agent2": make_member(org, RoleCode.SUPPORT_AGENT, email="agent2@acme.test"),
        "ops": make_member(org, RoleCode.OPS_MANAGER, email="ops@acme.test"),
        "tech": make_member(org, RoleCode.FIELD_TECHNICIAN, email="tech@acme.test"),
    }


@pytest.fixture
def ticket(client_for, team, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        r = client_for(team["ops"]).post(
            "/api/v1/tickets/",
            {
                "title": "ATM offline",
                "description": "Branch 4",
                "customer": str(team["customer"].id),
                "priority": "high",
            },
            format="json",
        )
    assert r.status_code == 201, r.json()
    return Ticket.objects.get(pk=r.json()["id"])


def assign(client, ticket, member, run):
    with run(execute=True):
        r = client.post(f"/api/v1/tickets/{ticket.id}/assign/", {"agent": str(member.user.id)}, format="json")
    assert r.status_code == 200, r.json()


def inbox(member):
    return list(Notification.objects.filter(recipient=member.user, in_app=True).values_list("type", flat=True))


# ------------------------------------------------------------------ fan-out
def test_assignment_notifies_the_assignee_in_app_and_by_email(
    client_for, team, ticket, django_capture_on_commit_callbacks
):
    assign(client_for(team["ops"]), ticket, team["agent"], django_capture_on_commit_callbacks)
    n = Notification.objects.get(recipient=team["agent"].user)
    assert n.type == "ticket_assigned" and n.link == f"/tickets/{ticket.id}" and ticket.reference in n.title
    assert inbox(team["ops"]) == []  # the person who acted isn't notified
    assert n.deliveries.get().status == "sent"
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["agent@acme.test"]
    assert f"/tickets/{ticket.id}" in mail.outbox[0].body
    assert mail.outbox[0].extra_headers["Auto-Submitted"] == "auto-generated"  # never answered by mailboxes


def test_assigning_yourself_sends_nothing(client_for, team, ticket, django_capture_on_commit_callbacks):
    assign(client_for(team["ops"]), ticket, team["ops"], django_capture_on_commit_callbacks)
    assert Notification.objects.count() == 0


def test_preferences_control_channels(client_for, team, ticket, django_capture_on_commit_callbacks):
    agent = client_for(team["agent"])
    prefs = agent.get("/api/v1/notifications/preferences/").json()
    assert {"type": "ticket_assigned", "label": "Ticket assigned to me", "channel": "email", "enabled": True} in prefs
    r = agent.put(
        "/api/v1/notifications/preferences/",
        [
            {"type": "ticket_assigned", "channel": "in_app", "enabled": False},
        ],
        format="json",
    )
    assert r.status_code == 200
    assign(client_for(team["ops"]), ticket, team["agent"], django_capture_on_commit_callbacks)
    n = Notification.objects.get(recipient=team["agent"].user)
    assert n.in_app is False and len(mail.outbox) == 1  # email only
    assert agent.get("/api/v1/notifications/").json()["count"] == 0

    agent.put(
        "/api/v1/notifications/preferences/",
        [{"type": "ticket_assigned", "channel": "email", "enabled": False}],
        format="json",
    )
    assign(client_for(team["ops"]), ticket, team["agent2"], django_capture_on_commit_callbacks)
    assign(client_for(team["ops"]), ticket, team["agent"], django_capture_on_commit_callbacks)
    assert Notification.objects.filter(recipient=team["agent"].user).count() == 1  # both channels off: nothing new


def test_inactive_members_are_not_notified(team, org):
    team["agent"].is_active = False
    team["agent"].save()
    assert services.notify(organization=org, recipients=[team["agent"].user], type="ticket_assigned", title="x") == []


def test_customer_reply_and_reopen_notify_the_agent(
    client_for, team, ticket, org, make_member, django_capture_on_commit_callbacks
):
    assign(client_for(team["ops"]), ticket, team["agent"], django_capture_on_commit_callbacks)
    portal = make_member(org, RoleCode.CUSTOMER, email="cust@bank.test")
    team["customer"].contacts.create(name="Cust", email="cust@bank.test", user=portal.user)
    with django_capture_on_commit_callbacks(execute=True):
        client_for(portal).post(f"/api/v1/tickets/{ticket.id}/comments/", {"body": "Any news?"}, format="json")
    assert "customer_reply" in inbox(team["agent"])

    with django_capture_on_commit_callbacks(execute=True):
        client_for(team["agent"]).post(
            f"/api/v1/tickets/{ticket.id}/transition/",
            {"status": "resolved", "resolution_notes": "Rebooted"},
            format="json",
        )
        r = client_for(portal).post(f"/api/v1/tickets/{ticket.id}/transition/", {"status": "reopened"}, format="json")
    assert r.status_code == 200, r.json()
    assert "ticket_reopened" in inbox(team["agent"])


def test_sla_warning_goes_to_the_owner_and_breach_also_to_managers(
    client_for, team, ticket, org, django_capture_on_commit_callbacks
):
    SLAPolicy.objects.filter(organization=org).update(business_hours=None, escalate_on_breach=False)
    # The clock already started on the working-hours calendar (a snapshot); switch this one to 24/7 too.
    SLAInstance.objects.filter(ticket=ticket).update(business_hours=None)
    Ticket.objects.filter(pk=ticket.pk).update(priority="medium")
    sla_services.sync_ticket(ticket.pk)  # retarget on the 24/7 calendar
    assign(client_for(team["ops"]), ticket, team["agent"], django_capture_on_commit_callbacks)
    start = ticket.sla.started_at
    with django_capture_on_commit_callbacks(execute=True):
        sla_services.scan(now=start + timedelta(hours=3, minutes=30))  # 4 h response target, 80 % = 3 h 12 m
    assert "sla_warning" in inbox(team["agent"]) and "sla_warning" not in inbox(team["ops"])
    with django_capture_on_commit_callbacks(execute=True):
        sla_services.scan(now=start + timedelta(hours=4, minutes=1))
    assert "sla_breached" in inbox(team["agent"]) and "sla_breached" in inbox(team["ops"])


def test_work_order_assignment_and_completion(client_for, team, ticket, django_capture_on_commit_callbacks):
    tech = Technician.objects.get(user=team["tech"].user)
    with django_capture_on_commit_callbacks(execute=True):
        r = client_for(team["ops"]).post(
            "/api/v1/work-orders/", {"ticket": str(ticket.id), "technician": str(tech.id)}, format="json"
        )
    assert r.status_code == 201, r.json()
    assert inbox(team["tech"]) == ["work_order_assigned"]
    wo = r.json()
    with django_capture_on_commit_callbacks(execute=True):
        client_for(team["ops"]).post(
            f"/api/v1/work-orders/{wo['id']}/cancel/", {"reason": "Fixed remotely"}, format="json"
        )
    assert "work_order_updated" in inbox(team["tech"])


# --------------------------------------------------------------------- inbox
def test_inbox_is_private_and_supports_read_state(client_for, team, org, other_org, make_member):
    mine = services.notify(organization=org, recipients=[team["agent"].user], type="ticket_assigned", title="One")[0]
    services.notify(organization=org, recipients=[team["agent"].user], type="ticket_assigned", title="Two")
    services.notify(organization=org, recipients=[team["agent2"].user], type="ticket_assigned", title="Not mine")
    elsewhere = make_member(other_org, RoleCode.SUPPORT_AGENT, email="agent@acme.test")  # same user, other org
    services.notify(organization=other_org, recipients=[elsewhere.user], type="ticket_assigned", title="Other org")

    agent = client_for(team["agent"])
    assert agent.get("/api/v1/notifications/").json()["count"] == 2
    assert agent.get("/api/v1/notifications/unread-count/").json() == {"unread": 2}
    assert agent.post(f"/api/v1/notifications/{mine.id}/read/").json()["is_read"] is True
    assert agent.get("/api/v1/notifications/?unread=1").json()["count"] == 1
    assert agent.post("/api/v1/notifications/read-all/", {}, format="json").json() == {"unread": 0}
    other = Notification.objects.get(title="Not mine")
    assert agent.post(f"/api/v1/notifications/{other.id}/read/").status_code == 404
    assert Notification.objects.get(title="Other org").read_at is None  # read-all is per organization


# ---------------------------------------------------------------- delivery
def test_email_delivery_retries_then_fails_and_never_double_sends(team, org):
    # Callbacks aren't run here: the test drives each worker attempt itself. Called directly,
    # `self.retry()` re-raises the original error, which is what schedules the next attempt on a worker.
    services.notify(organization=org, recipients=[team["agent"].user], type="ticket_assigned", title="x")
    d = NotificationDelivery.objects.get()
    with mock.patch("apps.notifications.tasks.EmailMessage.send", side_effect=OSError("SMTP down")) as send:
        for _ in range(4):
            with pytest.raises(OSError):
                deliver_email.run(str(d.id))
        assert deliver_email.run(str(d.id)) == "failed"  # gives up after 5 attempts
        assert deliver_email.run(str(d.id)) == "skipped"  # and stays failed
    d.refresh_from_db()
    assert (d.status, d.attempts, d.last_error) == ("failed", 5, "SMTP down") and send.call_count == 5

    d.status = "pending"
    d.save()
    assert deliver_email.run(str(d.id)) == "sent"
    assert deliver_email.run(str(d.id)) == "skipped"  # never sent twice
    assert len(mail.outbox) == 1


# ---------------------------------------------------------------- WhatsApp
def _whatsapp(org, template="att_notification"):
    from apps.integrations.models import Integration

    i = Integration.objects.create(
        organization=org,
        kind="whatsapp",
        provider="meta_cloud",
        name=f"WhatsApp {template or 'none'}",
        config={"phone_number_id": "123", **({"notification_template": template} if template else {})},
    )
    i.set_secret("access_token", "EAAG-token")
    return i


def test_e164_normalisation():
    assert services.e164("+977 984-720 6256") == "+9779847206256"
    assert services.e164("9847206256") is None and services.e164("") is None


def test_whatsapp_is_offered_only_when_an_integration_can_send(client_for, team, org):
    agent = client_for(team["agent"])
    assert {p["channel"] for p in agent.get("/api/v1/notifications/preferences/").json()} == {"in_app", "email"}
    _whatsapp(org, template="")  # no notification template yet
    assert {p["channel"] for p in agent.get("/api/v1/notifications/preferences/").json()} == {"in_app", "email"}
    _whatsapp(org)
    prefs = agent.get("/api/v1/notifications/preferences/").json()
    assert {"type": "sla_breached", "label": "SLA breached", "channel": "whatsapp", "enabled": False} in prefs


def test_whatsapp_notification_sends_the_template(team, org, django_capture_on_commit_callbacks):
    from apps.integrations import net

    _whatsapp(org)
    user = team["agent"].user
    user.phone = "+977 984-720 6256"
    user.save()
    services.set_preferences(
        user,
        org,
        [
            {"type": "ticket_assigned", "channel": "whatsapp", "enabled": True},
            {"type": "ticket_assigned", "channel": "email", "enabled": False},
        ],
    )
    sent = {}

    def fake_request(method, url, *, body=None, headers=None, timeout=None):
        sent["body"] = json.loads(body)
        return net.Response(200, b'{"messages": [{"id": "wamid.1"}]}', {}, 5)

    with mock.patch.object(net, "request", fake_request), django_capture_on_commit_callbacks(execute=True):
        services.notify(
            organization=org,
            recipients=[user],
            type="ticket_assigned",
            title="TCK-000046\nassigned to you",
            link="/tickets/abc",
        )
    d = NotificationDelivery.objects.get(channel="whatsapp")
    assert d.status == "sent" and not NotificationDelivery.objects.filter(channel="email").exists()
    tpl = sent["body"]["template"]
    assert sent["body"]["to"] == "9779847206256" and tpl["name"] == "att_notification"
    assert [p["text"] for p in tpl["components"][0]["parameters"]] == [
        "TCK-000046 assigned to you",
        "http://localhost:5173/tickets/abc",
    ]


def test_whatsapp_needs_a_phone_and_does_not_retry_recipient_errors(team, org, django_capture_on_commit_callbacks):
    from apps.integrations import net

    _whatsapp(org)
    user = team["agent"].user
    services.set_preferences(user, org, [{"type": "ticket_assigned", "channel": "whatsapp", "enabled": True}])
    services.notify(organization=org, recipients=[user], type="ticket_assigned", title="x")  # no phone on profile
    assert not NotificationDelivery.objects.filter(channel="whatsapp").exists()

    user.phone = "+9779847206256"
    user.save()
    services.notify(organization=org, recipients=[user], type="ticket_assigned", title="y")
    d = NotificationDelivery.objects.get(channel="whatsapp")
    refused = net.Response(
        400, b'{"error": {"message": "(#131030) Recipient phone number not in allowed list"}}', {}, 5
    )
    with mock.patch.object(net, "request", return_value=refused):
        from apps.notifications.tasks import deliver_whatsapp

        assert deliver_whatsapp.run(str(d.id)) == "failed"
    d.refresh_from_db()
    assert d.attempts == 1 and "131030" in d.last_error
