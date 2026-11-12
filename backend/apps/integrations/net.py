"""
The single egress path for tenant-configured URLs (webhooks, provider APIs).

SSRF protection:
- https only, unless WEBHOOKS_ALLOW_HTTP (dev/test);
- no credentials in the URL;
- the host is resolved once and every address must be public (no private,
  loopback, link-local, multicast, reserved or unspecified ranges, including
  IPv4-mapped IPv6);
- the connection is made to the vetted IP (TLS still verifies the hostname), so a
  second DNS answer can't redirect the request to an internal service (rebinding);
- redirects are never followed and response bodies are capped.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

from django.conf import settings

MAX_RESPONSE_BYTES = 64 * 1024


class UnsafeURL(ValueError):
    """The URL may not be called (scheme, credentials or a non-public address)."""


class EgressError(Exception):
    """Network failure talking to the remote (DNS, connect, TLS, timeout)."""


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict[str, str]
    duration_ms: int

    def json(self):
        return json.loads(self.body or b"null")

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def check_url(url: str, *, allow_http: bool | None = None) -> tuple[str, str, int, str]:
    """Validate shape (no DNS). Returns (scheme, host, port, path_with_query)."""
    allow_http = settings.WEBHOOKS_ALLOW_HTTP if allow_http is None else allow_http
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or (parts.scheme == "http" and not allow_http):
        raise UnsafeURL("Use an https:// URL.")
    if parts.username or parts.password:
        raise UnsafeURL("Don't put credentials in the URL.")
    if not parts.hostname:
        raise UnsafeURL("The URL needs a host name.")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeURL("Invalid port.") from exc
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return parts.scheme, parts.hostname, port, path


def resolve_public(host: str, port: int) -> str:
    """Resolve `host`; every address must be public. Returns the address to connect to."""
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [literal]
    else:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise EgressError(f"Can't resolve {host}.") from exc
        addresses = [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]
    if not addresses:
        raise EgressError(f"Can't resolve {host}.")
    if not all(_is_public(a) for a in addresses):
        raise UnsafeURL("That address is on a private or reserved network.")
    return str(addresses[0])


def validate_public_url(url: str) -> None:
    """Full check used when saving a URL (shape + DNS)."""
    _, host, port, _ = check_url(url)
    resolve_public(host, port)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


def request(
    method: str,
    url: str,
    *,
    body: bytes | None = None,
    headers: dict | None = None,
    timeout: float | None = None,
) -> Response:
    """Make one HTTP request to a public address. Raises UnsafeURL or EgressError; never follows redirects."""
    scheme, host, port, path = check_url(url)
    ip = resolve_public(host, port)
    timeout = timeout or settings.WEBHOOK_TIMEOUT_SECONDS
    conn_cls = _PinnedHTTPSConnection if scheme == "https" else _PinnedHTTPConnection
    conn = conn_cls(host, port, ip, timeout)
    started = time.monotonic()
    try:
        conn.request(method, path, body=body, headers={"User-Agent": "ATT-Platform/1", **(headers or {})})
        resp = conn.getresponse()
        data = resp.read(MAX_RESPONSE_BYTES)
        return Response(
            status=resp.status,
            body=data,
            headers={k.lower(): v for k, v in resp.getheaders()},
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except (OSError, http.client.HTTPException) as exc:  # timeouts, refused, TLS errors
        raise EgressError(f"{type(exc).__name__}: {exc}"[:300]) from exc
    finally:
        conn.close()


def post_json(url: str, payload, *, headers: dict | None = None, timeout: float | None = None) -> Response:
    return request(
        "POST",
        url,
        body=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        timeout=timeout,
    )


def post_form(url: str, fields: dict, *, headers: dict | None = None, timeout: float | None = None) -> Response:
    return request(
        "POST",
        url,
        body=urlencode(fields).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", **(headers or {})},
        timeout=timeout,
    )
