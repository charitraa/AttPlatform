"""
Webhook signatures (outbound, and the generic inbound connector).

    X-ATT-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, f"{t}.{raw body}")>

Receivers verify by recomputing the HMAC over the raw body and rejecting
timestamps outside a tolerance window (replay protection).
"""

import hashlib
import hmac
import time

HEADER = "X-ATT-Signature"
TOLERANCE_SECONDS = 300


def sign(secret: str, body: bytes, *, timestamp: int | None = None) -> str:
    t = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={digest}"


def verify(
    secret: str, header: str | None, body: bytes, *, now: float | None = None, tolerance: int = TOLERANCE_SECONDS
) -> bool:
    if not header or not secret:
        return False
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        t = int(parts["t"])
    except (KeyError, ValueError):
        return False
    if abs((time.time() if now is None else now) - t) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts.get("v1", ""))
