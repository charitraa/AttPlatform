"""
Authenticated event stream: `/ws/events/`.

Protocol
  client → {"type": "auth", "token": "<access JWT>", "organization": "<slug, optional>"}
  server → {"type": "auth.ok", "organization": "<slug>"}   (or auth.error, then close 4401)
  server → {"type": "notification.created" | "ticket.changed" | "work_order.changed" | "sla.changed", ...}
  server → {"type": "auth.expired"} then close 4401 when the access token expires; the client
           refreshes its token and reconnects.

The token travels in the first message rather than the URL so it never lands in
proxy access logs. Groups are derived server-side from the membership; payloads
carry IDs only and clients re-read through the REST API.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import AccessToken

from . import realtime

AUTH_TIMEOUT_SECONDS = 10
UNAUTHORIZED = 4401


@database_sync_to_async
def resolve_connection(token: str, slug: str | None):
    from apps.accounts.models import User
    from apps.organizations.tenancy import active_memberships, permissions_for

    try:
        access = AccessToken(token)
    except TokenError:
        return None
    user = User.objects.filter(pk=access.get(api_settings.USER_ID_CLAIM), is_active=True).first()
    if user is None:
        return None
    memberships = active_memberships(user)
    membership = memberships.filter(organization__slug=slug).first() if slug else memberships.first()
    if membership is None:
        return None
    perms = permissions_for(membership)
    org_id = membership.organization_id
    groups = [realtime.user_group(user.pk, org_id)]
    if "tickets.view_all" in perms:
        groups.append(realtime.staff_group(org_id))
    if "work_orders.view_all" in perms:
        groups.append(realtime.dispatch_group(org_id))
    return {"groups": groups, "organization": membership.organization.slug, "exp": int(access["exp"])}


class EventsConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.joined: list[str] = []
        self.authenticated = False
        self.timers: list[asyncio.Task] = []
        await self.accept()
        self.timers.append(asyncio.create_task(self._close_after(AUTH_TIMEOUT_SECONDS, unless_authenticated=True)))

    async def _close_after(self, seconds: float, *, unless_authenticated=False, message=None):
        await asyncio.sleep(max(0, seconds))
        if unless_authenticated and self.authenticated:
            return
        if message:
            await self.send_json(message)
        await self.close(code=UNAUTHORIZED)

    async def receive_json(self, content, **kwargs):
        kind = content.get("type") if isinstance(content, dict) else None
        if kind == "ping":
            await self.send_json({"type": "pong"})
        elif kind == "auth" and not self.authenticated:
            await self._authenticate(content)
        elif not self.authenticated:
            await self.send_json({"type": "auth.error", "message": "Authenticate first."})
            await self.close(code=UNAUTHORIZED)
        else:
            await self.send_json({"type": "error", "message": "Unsupported message type."})

    async def _authenticate(self, content: dict):
        token, slug = content.get("token"), content.get("organization")
        info = await resolve_connection(token, slug) if isinstance(token, str) and token else None
        if info is None:
            await self.send_json({"type": "auth.error", "message": "Invalid or expired token."})
            await self.close(code=UNAUTHORIZED)
            return
        for group in info["groups"]:
            await self.channel_layer.group_add(group, self.channel_name)
            self.joined.append(group)
        self.authenticated = True
        self.timers.append(
            asyncio.create_task(self._close_after(info["exp"] - time.time(), message={"type": "auth.expired"}))
        )
        await self.send_json({"type": "auth.ok", "organization": info["organization"]})

    async def disconnect(self, code):
        for task in self.timers:
            task.cancel()
        for group in self.joined:
            with contextlib.suppress(Exception):
                await self.channel_layer.group_discard(group, self.channel_name)

    async def event_push(self, message):
        if self.authenticated:
            await self.send_json({"type": message["event"], **message["data"]})
