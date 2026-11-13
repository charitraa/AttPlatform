"""
Every API endpoint must refuse anonymous requests, except a short, reviewed allowlist.

The test walks the URL resolver, so an endpoint added later without authentication
fails here instead of shipping open.
"""

import re

import pytest
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db
DUMMY_UUID = "00000000-0000-4000-8000-000000000000"

# Public on purpose. Each entry needs a reason.
PUBLIC = {
    "api/v1/health/": "liveness probe",
    "api/v1/health/ready/": "readiness probe (no secrets: component status only)",
    "api/v1/meta/": "public app config (name, version, demo-AI flag)",
    "api/v1/auth/login/": "sign-in",
    "api/v1/auth/refresh/": "token refresh from the HttpOnly cookie",
    "api/v1/auth/logout/": "sign-out clears the cookie",
    "api/v1/auth/register/": "organization sign-up",
    "api/v1/auth/password/forgot/": "password reset request",
    "api/v1/auth/password/reset/": "password reset with a signed token",
    "api/v1/auth/invitations/preview/": "invitation preview with a signed token",
    "api/v1/auth/invitations/accept/": "invitation acceptance with a signed token",
    "api/v1/webhooks/inbound/<uuid>/": "signed inbound webhooks (HMAC, not a session)",
    "api/v1/schema/": "OpenAPI schema",
    "api/v1/docs/": "Swagger UI",
    "api/v1/redoc/": "ReDoc",
}


def _walk(patterns, prefix=""):
    for p in patterns:
        if isinstance(p, URLResolver):
            yield from _walk(p.url_patterns, prefix + str(p.pattern))
        elif isinstance(p, URLPattern):
            yield prefix + str(p.pattern), p


def _concrete(route: str) -> str | None:
    """Turn a (possibly regex) route into a path we can call; None for format-suffix variants."""
    if "format" in route:
        return None
    route = route.replace("^", "").replace("$", "")
    route = re.sub(r"<uuid:[^>]+>", DUMMY_UUID, route)
    route = re.sub(r"<(?:int:|slug:|str:)?[^>]+>", "1", route)
    route = re.sub(r"\(\?P<\w+>[^)]*\)", DUMMY_UUID, route)  # router groups such as (?P<pk>[^/.]+)
    route = route.replace("/?", "/").replace("\\.", ".")
    return route if not re.search(r"[()\[\]*+?\\]", route) else None


def _api_routes():
    routes = {}
    for route, pattern in _walk(get_resolver().url_patterns):
        if not route.startswith("api/v1/"):
            continue
        path = _concrete(route)
        if path:
            key = re.sub(DUMMY_UUID, "<uuid>", path)
            routes.setdefault(key, (path, pattern))
    return routes


def test_the_sweep_finds_the_api():
    assert len(_api_routes()) >= 65  # guard against the walker silently finding nothing (69 routes today)


@pytest.mark.parametrize("key", sorted(k for k in _api_routes() if k not in PUBLIC))
def test_endpoint_refuses_anonymous_requests(key):
    path, _ = _api_routes()[key]
    client = APIClient()
    for method in ("get", "post", "patch", "delete"):
        status = getattr(client, method)(f"/{path}", {}, format="json").status_code
        assert status in (401, 403), f"{method.upper()} /{path} answered {status} without authentication"


def test_public_allowlist_is_current():
    """Every allowlisted route still exists (stale entries would hide nothing but mislead readers)."""
    missing = [k for k in PUBLIC if k not in _api_routes()]
    assert missing == []
