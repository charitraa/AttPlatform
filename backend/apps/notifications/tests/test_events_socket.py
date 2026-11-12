from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from rest_framework_simplejwt.tokens import AccessToken

from apps.notifications import realtime, services
from apps.organizations.catalog import RoleCode
from config.asgi import application

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]
ORIGIN = [(b"origin", b"http://localhost")]


async def connect():
    ws = WebsocketCommunicator(application, "/ws/events/", headers=ORIGIN)
    connected, _ = await ws.connect()
    assert connected
    return ws


async def authed(user, **extra):
    ws = await connect()
    await ws.send_json_to({"type": "auth", "token": str(AccessToken.for_user(user)), **extra})
    return ws, await ws.receive_json_from()


@pytest.fixture
def members(org, make_member):
    return {
        "agent": make_member(org, RoleCode.SUPPORT_AGENT, email="agent@acme.test"),
        "customer": make_member(org, RoleCode.CUSTOMER, email="cust@acme.test"),
    }


async def test_authenticated_user_receives_their_notifications(members, org):
    ws, ok = await authed(members["agent"].user)
    assert ok == {"type": "auth.ok", "organization": org.slug}
    await sync_to_async(services.notify)(
        organization=org, recipients=[members["agent"].user], type="ticket_assigned", title="TCK-1 assigned"
    )
    # notify() pushes after commit; transaction=True tests autocommit, so it has already happened.
    msg = await ws.receive_json_from()
    assert (msg["type"], msg["kind"], msg["title"]) == ("notification.created", "ticket_assigned", "TCK-1 assigned")
    await ws.disconnect()


async def test_only_staff_join_the_ticket_stream(members, org):
    agent, _ = await authed(members["agent"].user)
    customer, ok = await authed(members["customer"].user)
    assert ok["type"] == "auth.ok"
    await sync_to_async(realtime.push)(realtime.staff_group(org.id), "ticket.changed", ticket_id="t-1")
    assert (await agent.receive_json_from())["type"] == "ticket.changed"
    assert await customer.receive_nothing(timeout=0.2)
    await agent.disconnect()
    await customer.disconnect()


async def test_invalid_token_and_unauthenticated_messages_are_refused(members):
    ws = await connect()
    await ws.send_json_to({"type": "auth", "token": "not-a-jwt"})
    assert (await ws.receive_json_from())["type"] == "auth.error"
    assert (await ws.receive_output())["type"] == "websocket.close"

    ws = await connect()
    await ws.send_json_to({"type": "subscribe", "group": "o.anything.staff"})
    assert (await ws.receive_json_from())["type"] == "auth.error"
    assert (await ws.receive_output())["code"] == 4401


async def test_non_member_of_requested_organization_is_refused(members, other_org):
    ws, msg = await authed(members["agent"].user, organization=other_org.slug)
    assert msg["type"] == "auth.error"


async def test_connection_closes_when_the_access_token_expires(members):
    token = AccessToken.for_user(members["agent"].user)
    token.set_exp(lifetime=timedelta(seconds=1))
    ws = await connect()
    await ws.send_json_to({"type": "auth", "token": str(token)})
    assert (await ws.receive_json_from())["type"] == "auth.ok"
    assert (await ws.receive_json_from(timeout=3))["type"] == "auth.expired"
    assert (await ws.receive_output(timeout=1))["code"] == 4401
