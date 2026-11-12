"""
Email → tickets by polling an IMAP mailbox.

Safe on a shared, personal inbox:
- only messages addressed to the configured `only_to` address (e.g. a plus-address such as
  you+att@example.com) are read — searched on the server, then re-checked in the headers;
- only messages that arrived after the integration was created;
- the folder is opened read-only and bodies are fetched with BODY.PEEK, so nothing is marked
  read, moved or deleted;
- automatic mail (Auto-Submitted, bulk/list Precedence, our own notifications) is skipped, so a
  notification can never create a ticket;
- each message becomes at most one ticket (WebhookEvent is unique per Message-ID).

The IMAP connection goes through the same public-address check as webhooks and connects to
the vetted IP while TLS still verifies the host name.
"""

from __future__ import annotations

import email
import imaplib
import re
import socket
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from email.policy import default as default_policy
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

from django.utils import timezone

from . import net

MAX_PER_POLL = 50
MAX_BODY = 20000
OUR_HEADER = "X-ATT-Notification"


class _PinnedIMAP4SSL(imaplib.IMAP4_SSL):
    def __init__(self, host, port, ip, timeout):
        self._ip = ip
        super().__init__(host, port, ssl_context=ssl.create_default_context(), timeout=timeout)

    def _create_socket(self, timeout):
        sock = socket.create_connection((self._ip, self.port), timeout)
        return self.ssl_context.wrap_socket(sock, server_hostname=self.host)


def connect(host: str, port: int, username: str, password: str, *, timeout: float = 20.0) -> imaplib.IMAP4_SSL:
    ip = net.resolve_public(host, port)
    client = _PinnedIMAP4SSL(host, port, ip, timeout)
    client.login(username, password)
    return client


# ------------------------------------------------------------------ parsing
class _TextFromHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag in ("br", "p", "div", "li", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _html_to_text(html: str) -> str:
    p = _TextFromHTML()
    p.feed(html)
    return re.sub(r"\n{3,}", "\n\n", "".join(p.parts)).strip()


_QUOTE_MARKERS = (
    re.compile(r"^On .{5,200} wrote:\s*$", re.MULTILINE),
    re.compile(r"^-{2,} ?Original Message ?-{2,}", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^From: .+$\n^(Sent|Date): ", re.MULTILINE),
)


def strip_quoted(text: str) -> str:
    """Drop the quoted earlier conversation from a reply ("On … wrote:", "> …")."""
    cut = len(text)
    for marker in _QUOTE_MARKERS:
        m = marker.search(text)
        if m:
            cut = min(cut, m.start())
    kept = [line for line in text[:cut].splitlines() if not line.startswith(">")]
    return "\n".join(kept).strip()


@dataclass
class Incoming:
    message_id: str
    sender_email: str
    sender_name: str
    subject: str
    body: str
    received_at: datetime | None
    recipients: list[str]
    automatic: bool


def parse(raw: bytes) -> Incoming:
    msg = email.message_from_bytes(raw, policy=default_policy)
    name, addr = parseaddr(str(msg.get("From", "")))
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if body_part is not None:
        content = body_part.get_content()
        body = _html_to_text(content) if body_part.get_content_type() == "text/html" else content
    recipients = [
        a.lower()
        for _, a in getaddresses(
            [str(v) for h in ("To", "Cc", "Delivered-To", "X-Original-To") for v in msg.get_all(h, [])]
        )
        if a
    ]
    auto = str(msg.get("Auto-Submitted", "no")).strip().lower()
    precedence = str(msg.get("Precedence", "")).strip().lower()
    try:
        received = parsedate_to_datetime(str(msg.get("Date"))) if msg.get("Date") else None
    except (TypeError, ValueError):
        received = None
    if received is not None and timezone.is_naive(received):  # "-0000" / no zone: treat as UTC
        received = received.replace(tzinfo=UTC)
    return Incoming(
        message_id=str(msg.get("Message-ID", "")).strip()[:200],
        sender_email=addr.lower(),
        sender_name=name,
        subject=str(msg.get("Subject", "")).strip(),
        body=strip_quoted(body)[:MAX_BODY],
        received_at=received,
        recipients=recipients,
        automatic=auto != "no"
        or precedence in ("bulk", "junk", "list")
        or msg.get(OUR_HEADER) is not None
        or msg.get("List-Unsubscribe") is not None,
    )


# ------------------------------------------------------------------ polling
def _imap_date(dt: datetime) -> str:
    return timezone.localtime(dt, timezone.get_fixed_timezone(0)).strftime("%d-%b-%Y")


def fetch_new(client, *, folder: str, only_to: str, since: datetime) -> list[tuple[str, Incoming]]:
    """Messages to `only_to` that arrived since `since`, as (uid key, parsed). Read-only; never marks seen."""
    status, _ = client.select(f'"{folder}"', readonly=True)
    if status != "OK":
        raise ValueError(f"Can't open the folder “{folder}”.")
    uidvalidity = (client.response("UIDVALIDITY")[1] or [b"0"])[0]
    uidvalidity = uidvalidity.decode() if isinstance(uidvalidity, bytes) else str(uidvalidity)
    status, data = client.uid("SEARCH", None, "SINCE", _imap_date(since), "TO", f'"{only_to}"')
    if status != "OK":
        raise ValueError("The mailbox search failed.")
    uids = (data[0] or b"").split()[-MAX_PER_POLL:]
    out = []
    for uid in uids:
        status, parts = client.uid("FETCH", uid, "(BODY.PEEK[])")
        raw = next((p[1] for p in parts or [] if isinstance(p, tuple) and len(p) > 1), None)
        if status != "OK" or raw is None:
            continue
        msg = parse(raw)
        if only_to.lower() not in msg.recipients:  # IMAP TO is a substring match; check exactly
            continue
        if msg.received_at and msg.received_at < since:
            continue
        out.append((f"imap-{uidvalidity}-{uid.decode() if isinstance(uid, bytes) else uid}", msg))
    return out
