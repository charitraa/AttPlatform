"""
Linking a person's Telegram chat (Telegram has no "send to this phone number" for bots).

1. The person asks to connect: we create a one-time code (15 minutes) and a t.me deep link.
2. They press Start in Telegram, which sends "/start <code>" to the bot.
3. `poll` reads the bot's updates (getUpdates; no public webhook needed), matches the code and
   stores the chat ID. "/stop" disconnects. The beat task polls every minute; the "check" API
   polls at once so the page can confirm immediately.
"""

from __future__ import annotations

import secrets

from django.core.cache import cache

from apps.integrations import logs
from apps.integrations.connectors import connector_for
from apps.integrations.connectors.base import ConnectorError
from apps.integrations.models import IntegrationLog

from .models import Channel, ChatLink

CODE_TTL = 15 * 60


def bot_username(integration) -> str:
    key = f"telegram:username:{integration.pk}"
    name = cache.get(key)
    if not name:
        name = connector_for(integration).call("getMe")["username"]
        cache.set(key, name, 3600)
    return name


def start_link(user, organization, integration) -> str:
    code = secrets.token_urlsafe(18)  # letters, digits, - and _: valid as a Telegram start parameter
    cache.set(f"telegram:link:{code}", (str(user.pk), str(organization.pk)), CODE_TTL)
    return f"https://t.me/{bot_username(integration)}?start={code}"


def poll(integration) -> dict:
    connector = connector_for(integration)
    offset_key = f"telegram:offset:{integration.pk}"
    try:
        updates = connector.call(
            "getUpdates", {"offset": cache.get(offset_key, 0), "timeout": 0, "allowed_updates": ["message"]}
        )
    except ConnectorError as exc:
        logs.record(integration, direction=IntegrationLog.Direction.INBOUND, operation="poll", ok=False, error=str(exc))
        return {"linked": 0, "error": str(exc)}
    linked = 0
    for update in updates or []:
        cache.set(offset_key, update["update_id"] + 1, None)
        msg = update.get("message") or {}
        text, chat = (msg.get("text") or "").strip(), msg.get("chat") or {}
        if not chat.get("id"):
            continue
        if text.startswith("/start"):
            linked += _link(integration, connector, text, chat)
        elif text == "/stop":
            ChatLink.objects.filter(
                organization=integration.organization, channel=Channel.TELEGRAM, address=str(chat["id"])
            ).delete()
            _reply(connector, chat["id"], "Disconnected. You won't get ATT Platform notifications here any more.")
    if updates:
        logs.record(
            integration,
            direction=IntegrationLog.Direction.INBOUND,
            operation="poll",
            ok=True,
            response=f"{len(updates)} update(s), {linked} chat(s) linked",
        )
    return {"linked": linked}


def _link(integration, connector, text: str, chat: dict) -> int:
    from apps.accounts.models import User

    parts = text.split(maxsplit=1)
    claim = cache.get(f"telegram:link:{parts[1]}") if len(parts) == 2 else None
    if not claim or claim[1] != str(integration.organization_id):
        _reply(
            connector,
            chat["id"],
            "This link has expired. Open ATT Platform → Notifications → Preferences and "
            "press “Connect Telegram” again.",
        )
        return 0
    cache.delete(f"telegram:link:{parts[1]}")
    user = User.objects.get(pk=claim[0])
    name = " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) or chat.get("username", "")
    ChatLink.objects.update_or_create(
        user=user,
        organization=integration.organization,
        channel=Channel.TELEGRAM,
        defaults={"address": str(chat["id"]), "display_name": name[:100]},
    )
    _reply(
        connector,
        chat["id"],
        f"Connected ✓ {user.first_name}, you'll get ATT Platform notifications here "
        "for the events you choose. Send /stop to disconnect.",
    )
    return 1


def _reply(connector, chat_id, text: str) -> None:
    try:
        connector.call("sendMessage", {"chat_id": chat_id, "text": text})
    except ConnectorError:
        pass  # linking already happened; a failed confirmation message isn't worth failing the poll
