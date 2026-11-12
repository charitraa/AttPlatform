import json
import threading
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from apps.customers.models import Customer
from apps.integrations import crypto, net, services, signing
from apps.integrations.models import (
    Integration,
    IntegrationCredential,
    IntegrationLog,
    WebhookDelivery,
    WebhookEndpoint,
    WebhookEvent,
)
from apps.organizations.catalog import RoleCode
from apps.tickets.models import Ticket, TicketComment

pytestmark = pytest.mark.django_db
HOOK_HOST = "hooks.example.com"  # resolved to the local test server below


# ------------------------------------------------------------- receiver
class Receiver:
    """A real HTTP server on 127.0.0.1 that records requests and answers with a scripted status."""

    def __init__(self):
        self.requests: list[dict] = []
        self.status = 200
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                receiver.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                self.send_response(receiver.status)
                if receiver.status in (301, 302):
                    self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
                self.end_headers()
                self.wfile.write(b'{"ok": true}')

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://{HOOK_HOST}:{self.port}/hooks"


@pytest.fixture
def receiver(monkeypatch):
    r = Receiver()
    real = net.resolve_public

    def resolve(host, port):
        return "127.0.0.1" if host == HOOK_HOST else real(host, port)

    monkeypatch.setattr(net, "resolve_public", resolve)
    yield r
    r.server.shutdown()


@pytest.fixture
def team(org, make_member):
    customer = Customer.objects.create(organization=org, name="Himalayan Bank")
    return {
        "customer": customer,
        "admin": make_member(org, RoleCode.ORG_ADMIN, email="admin@acme.test"),
        "ops": make_member(org, RoleCode.OPS_MANAGER, email="ops@acme.test"),
        "agent": make_member(org, RoleCode.SUPPORT_AGENT, email="agent@acme.test"),
    }


def webhook_integration(client, receiver, events=("ticket.created", "ticket.commented")):
    r = client.post("/api/v1/integrations/", {"kind": "webhook", "provider": "generic", "name": "ERP"}, format="json")
    assert r.status_code == 201, r.json()
    e = client.post(
        f"/api/v1/integrations/{r.json()['id']}/endpoints/",
        {"url": receiver.url, "events": list(events)},
        format="json",
    )
    assert e.status_code == 201, e.json()
    return r.json(), e.json()


def new_ticket(client_for, team, run):
    with run(execute=True):
        r = client_for(team["agent"]).post(
            "/api/v1/tickets/",
            {"title": "ATM offline", "description": "Branch 4", "customer": str(team["customer"].id)},
            format="json",
        )
    assert r.status_code == 201, r.json()
    return r.json()


# ---------------------------------------------------------------- crypto
def test_secrets_round_trip_and_survive_key_rotation(settings):
    old_only = ["R0tLlV3z2vS3m4y7aQ1b6c8d0e2f4g6h8i0j2k4m6n8="]
    settings.FIELD_ENCRYPTION_KEYS = old_only
    token = crypto.encrypt("s3cret-value")
    settings.FIELD_ENCRYPTION_KEYS = ["9cD8L1q8cGVZ9n0w0yE1o0iQm2l5x8yQv4o3P6m1xYc=", *old_only]  # new key first
    assert crypto.decrypt(token) == "s3cret-value"
    rotated = crypto.rotate(token)
    settings.FIELD_ENCRYPTION_KEYS = ["9cD8L1q8cGVZ9n0w0yE1o0iQm2l5x8yQv4o3P6m1xYc="]  # old key retired
    assert crypto.decrypt(rotated) == "s3cret-value"
    with pytest.raises(crypto.SecretUnavailable):
        crypto.decrypt(token)
    settings.FIELD_ENCRYPTION_KEYS = []
    with pytest.raises(ImproperlyConfigured):
        crypto.encrypt("x")


def test_credentials_are_write_only(client_for, team):
    client = client_for(team["admin"])
    r = client.post(
        "/api/v1/integrations/",
        {
            "kind": "sms",
            "provider": "twilio",
            "name": "Twilio",
            "config": {"from_number": "+15005550006"},
            "secrets": {"account_sid": "AC00000000000000000000000000000000", "auth_token": "tok-very-secret-9f3a"},
        },
        format="json",
    )
    assert r.status_code == 201, r.json()
    for body in (
        r.content,
        client.get(f"/api/v1/integrations/{r.json()['id']}/").content,
        client.get("/api/v1/integrations/").content,
    ):
        assert b"tok-very-secret" not in body and b"AC0000000000" not in body
    creds = r.json()["credentials"]
    assert creds["auth_token"] == {"configured": True, "hint": "…9f3a"}
    stored = IntegrationCredential.objects.get(key="auth_token")
    assert "tok-very-secret" not in stored.ciphertext and crypto.decrypt(stored.ciphertext) == "tok-very-secret-9f3a"
    # Updating without secrets keeps them; an empty value means "unchanged".
    client.patch(
        f"/api/v1/integrations/{r.json()['id']}/", {"name": "SMS", "secrets": {"auth_token": ""}}, format="json"
    )
    assert Integration.objects.get(pk=r.json()["id"]).secret("auth_token") == "tok-very-secret-9f3a"


def test_validation_permissions_and_isolation(client_for, team, other_org, make_member):
    admin = client_for(team["admin"])
    assert client_for(team["ops"]).get("/api/v1/integrations/").status_code == 403
    bad = admin.post(
        "/api/v1/integrations/", {"kind": "sms", "provider": "twilio", "name": "X", "config": {}}, format="json"
    )
    assert bad.status_code == 400 and {"config", "secrets"} & set(bad.json()["error"]["details"])
    assert (
        admin.post(
            "/api/v1/integrations/", {"kind": "sms", "provider": "carrier-pigeon", "name": "Y"}, format="json"
        ).status_code
        == 400
    )
    mine = admin.post(
        "/api/v1/integrations/", {"kind": "sms", "provider": "console", "name": "Dev SMS"}, format="json"
    ).json()
    outsider = client_for(make_member(other_org, RoleCode.ORG_ADMIN))
    assert outsider.get(f"/api/v1/integrations/{mine['id']}/").status_code == 404
    assert admin.patch(f"/api/v1/integrations/{mine['id']}/", {"provider": "twilio"}, format="json").status_code == 400


# ------------------------------------------------------------ SSRF guard
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://localhost/x",
        "http://10.0.0.5/x",
        "http://192.168.1.1/x",
        "http://172.16.0.1/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/x",
        "http://[::ffff:127.0.0.1]/x",
        "http://0.0.0.0/x",
    ],
)
def test_private_and_internal_addresses_are_refused(url):
    with pytest.raises(net.UnsafeURL):
        net.validate_public_url(url)


def test_url_shape_rules(settings):
    settings.WEBHOOKS_ALLOW_HTTP = False
    with pytest.raises(net.UnsafeURL, match="https"):
        net.check_url("http://example.com/hook")
    with pytest.raises(net.UnsafeURL, match="credentials"):
        net.check_url("https://user:pass@example.com/hook")
    with pytest.raises(net.UnsafeURL):
        net.check_url("ftp://example.com/x")


def test_a_public_name_resolving_to_a_private_address_is_refused():
    with (
        mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.1.2.3", 443))]),
        pytest.raises(net.UnsafeURL),
    ):
        net.validate_public_url("https://innocent.example.com/hook")


def test_endpoint_urls_are_checked_when_saved(client_for, team, receiver):
    client = client_for(team["admin"])
    integration, _ = webhook_integration(client, receiver)
    r = client.post(
        f"/api/v1/integrations/{integration['id']}/endpoints/",
        {"url": "http://169.254.169.254/latest/", "events": ["ticket.created"]},
        format="json",
    )
    assert r.status_code == 400 and "private" in str(r.json())


# -------------------------------------------------------------- outbound
def test_ticket_events_are_delivered_signed(client_for, team, receiver, django_capture_on_commit_callbacks):
    _, endpoint = webhook_integration(client_for(team["admin"]), receiver)
    assert endpoint["signing_secret"].startswith("whsec_")
    ticket = new_ticket(client_for, team, django_capture_on_commit_callbacks)

    assert len(receiver.requests) == 1
    req = receiver.requests[0]
    assert signing.verify(endpoint["signing_secret"], req["headers"]["X-ATT-Signature"], req["body"])
    envelope = json.loads(req["body"])
    assert envelope["type"] == "ticket.created" and req["headers"]["X-ATT-Event-Id"] == envelope["id"]
    assert envelope["data"]["ticket"]["reference"] == ticket["reference"]
    d = WebhookDelivery.objects.get()
    assert (d.status, d.attempts, d.response_code) == ("succeeded", 1, 200)
    assert IntegrationLog.objects.filter(operation="deliver ticket.created", status="ok").exists()


def test_internal_notes_are_never_sent(client_for, team, receiver, django_capture_on_commit_callbacks):
    webhook_integration(client_for(team["admin"]), receiver, events=("ticket.commented",))
    ticket = new_ticket(client_for, team, django_capture_on_commit_callbacks)
    agent = client_for(team["agent"])
    with django_capture_on_commit_callbacks(execute=True):
        agent.post(
            f"/api/v1/tickets/{ticket['id']}/comments/",
            {"body": "Secret plan", "visibility": "internal"},
            format="json",
        )
    assert receiver.requests == []
    with django_capture_on_commit_callbacks(execute=True):
        agent.post(
            f"/api/v1/tickets/{ticket['id']}/comments/", {"body": "On our way", "visibility": "public"}, format="json"
        )
    assert len(receiver.requests) == 1 and b"Secret plan" not in receiver.requests[0]["body"]


def test_failed_deliveries_retry_on_schedule_then_fail(client_for, team, receiver):
    _, endpoint = webhook_integration(client_for(team["admin"]), receiver)
    receiver.status = 500
    env = {"id": "a7d6e1f2-0000-4000-8000-000000000001", "type": "ticket.created", "data": {}}
    d = WebhookDelivery.objects.create(
        endpoint_id=endpoint["id"], event_id=env["id"], event_type="ticket.created", payload=env
    )
    before = timezone.now()
    assert services.deliver(d.pk) == "retrying"
    d.refresh_from_db()
    assert d.attempts == 1 and d.response_code == 500
    assert timedelta(seconds=55) < d.next_retry_at - before < timedelta(seconds=65)  # 1 minute
    for _ in range(4):
        assert services.deliver(d.pk) == "retrying"
    assert services.deliver(d.pk) == "failed"  # 6th attempt
    assert services.deliver(d.pk) == "failed"  # no-op afterwards
    assert len(receiver.requests) == 6
    assert len({r["headers"]["X-ATT-Event-Id"] for r in receiver.requests}) == 1  # same event id on every attempt

    receiver.status = 200
    services.redeliver(d)
    assert services.deliver(d.pk) == "succeeded"


def test_redirects_are_not_followed(client_for, team, receiver):
    _, endpoint = webhook_integration(client_for(team["admin"]), receiver)
    receiver.status = 302  # pointing at the cloud metadata service
    d = WebhookDelivery.objects.create(
        endpoint_id=endpoint["id"],
        event_id="a7d6e1f2-0000-4000-8000-000000000002",
        event_type="ticket.created",
        payload={"id": "x", "type": "ticket.created"},
    )
    assert services.deliver(d.pk) == "retrying"
    d.refresh_from_db()
    assert d.response_code == 302 and len(receiver.requests) == 1


def test_disabled_endpoints_fail_and_sweep_requeues_lost_retries(client_for, team, receiver):
    _, endpoint = webhook_integration(client_for(team["admin"]), receiver)
    stuck = WebhookDelivery.objects.create(
        endpoint_id=endpoint["id"],
        event_id="a7d6e1f2-0000-4000-8000-000000000003",
        event_type="ticket.created",
        payload={"id": "x", "type": "ticket.created"},
        status="retrying",
        attempts=2,
        next_retry_at=timezone.now() - timedelta(minutes=10),
    )
    with mock.patch.object(services, "_enqueue") as enqueue:
        assert services.sweep_due() == 1
    enqueue.assert_called_once_with(stuck.pk)
    WebhookEndpoint.objects.filter(pk=endpoint["id"]).update(is_active=False)
    assert services.deliver(stuck.pk) == "failed"


def test_test_connection_pings_endpoints(client_for, team, receiver):
    client = client_for(team["admin"])
    integration, _ = webhook_integration(client, receiver)
    r = client.post(f"/api/v1/integrations/{integration['id']}/test/").json()
    assert r["ok"] is True and json.loads(receiver.requests[0]["body"])["type"] == "ping"
    receiver.status = 503
    assert client.post(f"/api/v1/integrations/{integration['id']}/test/").json()["ok"] is False
    health = client.get(f"/api/v1/integrations/{integration['id']}/").json()
    assert health["health"] == "error" and "503" in health["last_error"]


# --------------------------------------------------------------- inbound
@pytest.fixture
def inbound(client_for, team):
    team["customer"].contacts.create(name="Sita Rai", email="sita@bank.test")
    r = client_for(team["admin"]).post(
        "/api/v1/integrations/",
        {"kind": "inbound", "provider": "generic", "name": "Mail bridge", "config": {"channel": "email"}},
        format="json",
    )
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["inbound_url"].endswith(f"/api/v1/webhooks/inbound/{body['id']}/")
    return body["id"], body["generated_secrets"]["signing_secret"]


def post_inbound(api_client, integration_id, secret, payload, *, timestamp=None, raw=None):
    body = raw if raw is not None else json.dumps(payload).encode()
    return api_client.post(
        f"/api/v1/webhooks/inbound/{integration_id}/",
        data=body,
        content_type="application/json",
        HTTP_X_ATT_SIGNATURE=signing.sign(secret, body, timestamp=timestamp),
    )


MSG = {
    "id": "msg-1",
    "from": {"email": "SITA@bank.test", "name": "Sita"},
    "subject": "Printer jammed",
    "body": "The 3rd floor printer is jammed again.",
}


def test_inbound_message_creates_a_ticket_once(api_client, inbound, team, django_capture_on_commit_callbacks):
    integration_id, secret = inbound
    with django_capture_on_commit_callbacks(execute=True):
        r = post_inbound(api_client, integration_id, secret, MSG)
    assert r.status_code == 202 and r.json()["duplicate"] is False
    event = WebhookEvent.objects.get()
    assert event.status == "processed" and event.result["action"] == "ticket"
    t = Ticket.objects.get(pk=event.result["ticket_id"])
    assert (t.title, t.channel, t.contact.email, t.customer_id) == (
        "Printer jammed",
        "email",
        "sita@bank.test",
        team["customer"].id,
    )
    with django_capture_on_commit_callbacks(execute=True):
        again = post_inbound(api_client, integration_id, secret, MSG)  # the sender retries
    assert again.status_code == 200 and again.json()["duplicate"] is True
    assert Ticket.objects.filter(title="Printer jammed").count() == 1


def test_inbound_signature_replay_size_and_unknown_integration(api_client, inbound, settings):
    integration_id, secret = inbound
    assert post_inbound(api_client, integration_id, "wrong-secret", MSG).status_code == 401
    assert post_inbound(api_client, integration_id, secret, MSG, timestamp=int(time.time()) - 600).status_code == 401
    unknown = "00000000-0000-4000-8000-000000000000"
    assert post_inbound(api_client, unknown, secret, MSG).status_code == 401  # same answer: nothing revealed
    settings.INBOUND_WEBHOOK_MAX_BYTES = 100
    assert post_inbound(api_client, integration_id, secret, {**MSG, "body": "x" * 500}).status_code == 413
    settings.INBOUND_WEBHOOK_MAX_BYTES = 256 * 1024
    assert (
        post_inbound(api_client, integration_id, secret, {k: v for k, v in MSG.items() if k != "id"}).status_code == 400
    )
    assert WebhookEvent.objects.count() == 0


def test_rotating_the_inbound_secret(client_for, team, api_client, inbound):
    integration_id, old = inbound
    new = (
        client_for(team["admin"]).post(f"/api/v1/integrations/{integration_id}/rotate-secret/").json()["signing_secret"]
    )
    assert new != old
    assert post_inbound(api_client, integration_id, old, {**MSG, "id": "m2"}).status_code == 401
    assert post_inbound(api_client, integration_id, new, {**MSG, "id": "m2"}).status_code == 202


def test_inbound_reply_by_reference(
    api_client, inbound, team, org, make_member, client_for, django_capture_on_commit_callbacks
):
    integration_id, secret = inbound
    ticket = new_ticket(client_for, team, django_capture_on_commit_callbacks)
    reply = {
        "id": "msg-2",
        "from": {"email": "sita@bank.test"},
        "subject": f"Re: [{ticket['reference']}] ATM",
        "body": "Still offline this morning.",
    }
    with django_capture_on_commit_callbacks(execute=True):
        post_inbound(api_client, integration_id, secret, reply)
    note = TicketComment.objects.get(ticket_id=ticket["id"], body__contains="Still offline")
    assert note.visibility == "internal" and "sita@bank.test" in note.body  # no portal account: kept internal

    portal = make_member(org, RoleCode.CUSTOMER, email="sita@bank.test")
    team["customer"].contacts.filter(email="sita@bank.test").update(user=portal.user)
    with django_capture_on_commit_callbacks(execute=True):
        post_inbound(api_client, integration_id, secret, {**reply, "id": "msg-3", "body": "Now it works, thanks!"})
    public = TicketComment.objects.get(ticket_id=ticket["id"], body="Now it works, thanks!")
    assert public.visibility == "public" and public.author_id == portal.user.id


def test_inbound_ignores_unknown_senders_and_stops_if_the_creator_loses_access(
    api_client, inbound, team, django_capture_on_commit_callbacks
):
    integration_id, secret = inbound
    with django_capture_on_commit_callbacks(execute=True):
        post_inbound(api_client, integration_id, secret, {**MSG, "id": "m4", "from": {"email": "who@nowhere.test"}})
    e = WebhookEvent.objects.get(external_id="m4")
    assert e.status == "ignored" and "No customer contact" in e.error
    team["admin"].is_active = False
    team["admin"].save()
    with django_capture_on_commit_callbacks(execute=True):
        post_inbound(api_client, integration_id, secret, {**MSG, "id": "m5"})
    assert "can no longer create tickets" in WebhookEvent.objects.get(external_id="m5").error


# ------------------------------------------------------------- messaging
def test_twilio_request_shape(client_for, team):
    client = client_for(team["admin"])
    i = client.post(
        "/api/v1/integrations/",
        {
            "kind": "sms",
            "provider": "twilio",
            "name": "Twilio",
            "config": {"from_number": "+15005550006"},
            "secrets": {"account_sid": "AC123", "auth_token": "tok"},
        },
        format="json",
    ).json()
    sent = {}

    def fake_request(method, url, *, body=None, headers=None, timeout=None):
        sent.update(method=method, url=url, body=body, headers=headers)
        return net.Response(201, b'{"sid": "SM1", "status": "queued"}', {}, 5)

    with mock.patch.object(net, "request", fake_request):
        r = client.post(
            f"/api/v1/integrations/{i['id']}/send-test/", {"to": "+9779812345678", "text": "Hi"}, format="json"
        )
    assert r.json() == {"provider_id": "SM1", "status": "queued"}
    assert sent["url"] == "https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json"
    assert b"To=%2B9779812345678" in sent["body"] and sent["headers"]["Authorization"].startswith("Basic ")
    log = IntegrationLog.objects.filter(integration_id=i["id"], operation="send").get()
    assert "+977…78" in log.request_summary and "9812345678" not in log.request_summary  # phone masked


def test_whatsapp_requires_a_template_and_console_sms_logs(client_for, team):
    client = client_for(team["admin"])
    wa = client.post(
        "/api/v1/integrations/",
        {
            "kind": "whatsapp",
            "provider": "meta_cloud",
            "name": "WhatsApp",
            "config": {"phone_number_id": "123"},
            "secrets": {"access_token": "EAAG-token"},
        },
        format="json",
    ).json()
    r = client.post(
        f"/api/v1/integrations/{wa['id']}/send-test/", {"to": "+9779812345678", "text": "free text"}, format="json"
    )
    assert r.status_code == 400 and "template" in str(r.json())
    console = client.post(
        "/api/v1/integrations/", {"kind": "sms", "provider": "console", "name": "Dev"}, format="json"
    ).json()
    ok = client.post(
        f"/api/v1/integrations/{console['id']}/send-test/", {"to": "+9779812345678", "text": "Hi"}, format="json"
    )
    assert ok.json()["status"] == "logged"
    assert client.get(f"/api/v1/integrations/{console['id']}/logs/").json()["count"] == 1


def test_twilio_with_an_api_key_and_number_check(client_for, team):
    client = client_for(team["admin"])
    assert (
        client.post(
            "/api/v1/integrations/",
            {
                "kind": "sms",
                "provider": "twilio",
                "name": "No creds",
                "config": {"from_number": "+15005550006"},
                "secrets": {"account_sid": "AC123"},
            },
            format="json",
        ).status_code
        == 400
    )  # needs a key or a token
    i = client.post(
        "/api/v1/integrations/",
        {
            "kind": "sms",
            "provider": "twilio",
            "name": "Twilio key",
            "config": {"from_number": "+15005550006"},
            "secrets": {"account_sid": "AC123", "api_key_sid": "SK999", "api_key_secret": "key-secret"},
        },
        format="json",
    )
    assert i.status_code == 201, i.json()
    seen = {}

    def fake_request(method, url, *, body=None, headers=None, timeout=None):
        import base64 as b64

        seen["url"], seen["user"] = url, b64.b64decode(headers["Authorization"].split()[1]).decode().split(":")[0]
        listed = [{"phone_number": "+15005550006", "capabilities": {"sms": True}}] if "15005550006" in url else []
        return net.Response(200, json.dumps({"incoming_phone_numbers": listed}).encode(), {}, 5)

    with mock.patch.object(net, "request", fake_request):
        r = client.post(f"/api/v1/integrations/{i.json()['id']}/test/").json()
    assert r == {"ok": True, "message": "Connected. +15005550006 is ready to send SMS."}
    assert (
        seen["user"] == "SK999"
        and "/Accounts/AC123/IncomingPhoneNumbers.json?PhoneNumber=%2B15005550006" in seen["url"]
    )
