import json
from unittest import mock

import pytest

from apps.integrations import net
from apps.integrations.models import Integration
from apps.notifications import services, telegram
from apps.notifications.models import ChatLink, NotificationDelivery
from apps.notifications.tasks import deliver_message
from apps.organizations.catalog import RoleCode

pytestmark = pytest.mark.django_db
TOKEN = "123456:ABC-secret-token"


@pytest.fixture
def agent(org, make_member):
    m = make_member(org, RoleCode.SUPPORT_AGENT, email="ana@acme.test")
    m.user.first_name = "Ana"
    m.user.save()
    return m


def integration(org, kind, provider, config=None, secrets=None, name=None):
    i = Integration.objects.create(
        organization=org, kind=kind, provider=provider, name=name or provider, config=config or {}
    )
    for k, v in (secrets or {}).items():
        i.set_secret(k, v)
    return i


class FakeHTTP:
    """Scripted responses per URL substring; records requests."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, method, url, *, body=None, headers=None, timeout=None):
        self.calls.append(
            {"method": method, "url": url, "body": json.loads(body) if body else None, "headers": headers}
        )
        for key, (status, payload) in self.routes.items():
            if key in url:
                data = payload(self.calls[-1]) if callable(payload) else payload
                return net.Response(status, json.dumps(data).encode(), {}, 5)
        raise AssertionError(f"unexpected request {url}")


# ------------------------------------------------------- Android gateway
def test_android_gateway_sends_and_checks_the_phone(client_for, org, make_member):
    admin = client_for(make_member(org, RoleCode.ORG_ADMIN))
    i = admin.post(
        "/api/v1/integrations/",
        {
            "kind": "sms",
            "provider": "android_gateway",
            "name": "My phone",
            "config": {"username": "ABCDEF"},
            "secrets": {"password": "pw-1234"},
        },
        format="json",
    ).json()
    http = FakeHTTP(
        {"/devices": (200, [{"id": "d1", "name": "Pixel 7"}]), "/message": (202, {"id": "m-1", "state": "Pending"})}
    )
    with mock.patch.object(net, "request", http):
        assert admin.post(f"/api/v1/integrations/{i['id']}/test/").json() == {
            "ok": True,
            "message": "Connected to Pixel 7.",
        }
        sent = admin.post(
            f"/api/v1/integrations/{i['id']}/send-test/", {"to": "+9779847206256", "text": "Hi"}, format="json"
        ).json()
    assert sent == {"provider_id": "m-1", "status": "pending"}
    send = http.calls[-1]
    assert send["url"] == "https://api.sms-gate.app/3rdparty/v1/message"
    assert send["body"] == {"message": "Hi", "phoneNumbers": ["+9779847206256"]}
    assert send["headers"]["Authorization"].startswith("Basic ")


def test_android_gateway_reports_wrong_credentials_and_no_phone(client_for, org, make_member):
    admin = client_for(make_member(org, RoleCode.ORG_ADMIN))
    i = admin.post(
        "/api/v1/integrations/",
        {
            "kind": "sms",
            "provider": "android_gateway",
            "name": "My phone",
            "config": {"username": "ABCDEF"},
            "secrets": {"password": "x"},
        },
        format="json",
    ).json()
    with mock.patch.object(net, "request", FakeHTTP({"/devices": (401, {"message": "unauthorized"})})):
        r = admin.post(f"/api/v1/integrations/{i['id']}/test/").json()
    assert r["ok"] is False and "rejected" in r["message"]
    with mock.patch.object(net, "request", FakeHTTP({"/devices": (200, [])})):
        assert "no phone is connected" in admin.post(f"/api/v1/integrations/{i['id']}/test/").json()["message"]


# --------------------------------------------------------------- Telegram
def test_telegram_link_flow(client_for, org, agent):
    bot = integration(org, "telegram", "bot", secrets={"bot_token": TOKEN})
    client = client_for(agent)
    channels = client.get("/api/v1/notifications/channels/").json()
    assert {"channel": "telegram", "ready": False, "help": "Connect your Telegram account.", "detail": ""} in channels

    http = FakeHTTP({"/getMe": (200, {"ok": True, "result": {"username": "att_demo_bot"}})})
    with mock.patch.object(net, "request", http):
        url = client.post("/api/v1/notifications/telegram/link/").json()["url"]
    assert url.startswith("https://t.me/att_demo_bot?start=")
    code = url.split("start=")[1]

    replies = []
    updates = [
        {"update_id": 10, "message": {"text": f"/start {code}", "chat": {"id": 777, "first_name": "Ana"}}},
        {"update_id": 11, "message": {"text": "/start expired-code", "chat": {"id": 888}}},
    ]
    http = FakeHTTP(
        {
            "/getUpdates": (200, lambda call: {"ok": True, "result": updates if call["body"]["offset"] == 0 else []}),
            "/sendMessage": (
                200,
                lambda call: replies.append(call["body"]) or {"ok": True, "result": {"message_id": 1}},
            ),
        }
    )
    with mock.patch.object(net, "request", http):
        assert client.post("/api/v1/notifications/telegram/check/").json() == {"linked": True}
        assert telegram.poll(bot) == {"linked": 0}  # offset moved on: the same updates aren't processed twice
    assert ChatLink.objects.get(user=agent.user).address == "777"
    assert "Connected" in replies[0]["text"] and "expired" in replies[1]["text"]
    assert {"channel": "telegram", "ready": True, "help": "", "detail": "Ana"} in client.get(
        "/api/v1/notifications/channels/"
    ).json()
    assert client.delete("/api/v1/notifications/telegram/link/").status_code == 204
    assert not ChatLink.objects.exists()


def test_telegram_errors_never_contain_the_token(org):
    bot = integration(org, "telegram", "bot", secrets={"bot_token": TOKEN})
    from apps.integrations.services import test_connection

    with mock.patch.object(
        net, "request", side_effect=net.EgressError(f"failed https://api.telegram.org/bot{TOKEN}/getMe")
    ):
        result = test_connection(bot)
    assert result.ok is False and TOKEN not in result.message and "secret-token" not in bot.logs.get().error


# --------------------------------------------------- notification channels
def test_sms_and_telegram_notifications_are_delivered(org, agent, django_capture_on_commit_callbacks):
    integration(org, "sms", "android_gateway", config={"username": "ABCDEF"}, secrets={"password": "pw"})
    integration(org, "telegram", "bot", secrets={"bot_token": TOKEN})
    user = agent.user
    user.phone = "+977 984 720 6256"
    user.save()
    ChatLink.objects.create(user=user, organization=org, channel="telegram", address="777")
    services.set_preferences(
        user, org, [{"type": "sla_breached", "channel": c, "enabled": True} for c in ("sms", "telegram")]
    )
    assert services.channels_for(org) == ["in_app", "email", "sms", "telegram"]
    http = FakeHTTP(
        {
            "/message": (202, {"id": "m-1", "state": "Pending"}),
            "/sendMessage": (200, {"ok": True, "result": {"message_id": 5}}),
        }
    )
    with mock.patch.object(net, "request", http), django_capture_on_commit_callbacks(execute=True):
        services.notify(
            organization=org, recipients=[user], type="sla_breached", title="TCK-000046 breached", link="/tickets/abc"
        )
    assert set(NotificationDelivery.objects.values_list("channel", "status")) == {
        ("email", "sent"),
        ("sms", "sent"),
        ("telegram", "sent"),
    }
    by_url = {c["url"].rsplit("/", 1)[-1]: c["body"] for c in http.calls}
    assert by_url["message"]["phoneNumbers"] == ["+9779847206256"]
    assert by_url["message"]["message"] == "Acme: TCK-000046 breached\nhttp://localhost:5173/tickets/abc"
    assert by_url["sendMessage"]["chat_id"] == "777"


def test_unlinked_or_phoneless_people_get_no_external_delivery(org, agent):
    integration(org, "telegram", "bot", secrets={"bot_token": TOKEN})
    services.set_preferences(
        agent.user,
        org,
        [
            {"type": "sla_breached", "channel": "telegram", "enabled": True},
            {"type": "sla_breached", "channel": "in_app", "enabled": False},
            {"type": "sla_breached", "channel": "email", "enabled": False},
        ],
    )
    assert services.notify(organization=org, recipients=[agent.user], type="sla_breached", title="x") == []
    d_ids = list(NotificationDelivery.objects.values_list("id", flat=True))
    assert d_ids == [] and deliver_message.run("00000000-0000-4000-8000-000000000000") == "skipped"
