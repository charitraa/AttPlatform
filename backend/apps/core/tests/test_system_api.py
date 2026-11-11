from unittest import mock

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_health_is_public_and_returns_version(api_client):
    response = api_client.get(reverse("health"))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert "timestamp" in body


def test_every_response_carries_request_id(api_client):
    response = api_client.get(reverse("health"))
    assert len(response["X-Request-ID"]) >= 8


def test_valid_client_request_id_is_echoed(api_client):
    response = api_client.get(reverse("health"), HTTP_X_REQUEST_ID="client-trace-1234")
    assert response["X-Request-ID"] == "client-trace-1234"


def test_unsafe_client_request_id_is_replaced(api_client):
    response = api_client.get(reverse("health"), HTTP_X_REQUEST_ID="bad id\nwith newline")
    assert response["X-Request-ID"] != "bad id\nwith newline"


def test_readiness_ok_when_dependencies_up(api_client):
    ok = {"status": "ok", "latency_ms": 1.0}
    with mock.patch.dict("apps.core.health.CHECKS", {"database": lambda: ok, "redis": lambda: ok}):
        response = api_client.get(reverse("health-ready"))
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_real_database_check_passes(api_client):
    # Database check runs against the real PostgreSQL test database.
    from apps.core.health import check_database

    assert check_database()["status"] == "ok"


def test_readiness_returns_503_when_a_dependency_fails(api_client):
    ok = {"status": "ok", "latency_ms": 1.0}
    bad = {"status": "error", "latency_ms": 2000.0}
    with mock.patch.dict("apps.core.health.CHECKS", {"database": lambda: ok, "redis": lambda: bad}):
        response = api_client.get(reverse("health-ready"))
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["redis"]["status"] == "error"


def test_meta_exposes_mock_mode_but_no_secrets(api_client, settings):
    settings.AI_API_KEY = "sk-secret-should-never-appear"
    response = api_client.get(reverse("meta"))
    assert response.status_code == 200
    assert response.json()["ai_mock_mode"] is True
    assert "sk-secret" not in response.content.decode()


def test_openapi_schema_is_generated(api_client):
    response = api_client.get(reverse("schema"), {"format": "json"})
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/health/" in paths
    assert "/api/v1/meta/" in paths


def test_clients_behind_proxy_get_separate_throttle_buckets(api_client, settings):
    """Regression: behind nginx every request has the proxy's REMOTE_ADDR."""
    from django.core.cache import cache
    from rest_framework.settings import api_settings
    from rest_framework.throttling import ScopedRateThrottle

    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1,
                               "DEFAULT_THROTTLE_RATES": {**settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
                                                          "system": "2/min"}}
    api_settings.reload()
    ScopedRateThrottle.THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES
    cache.clear()
    try:
        url = reverse("health")
        proxy = {"REMOTE_ADDR": "172.19.0.6"}
        a = [api_client.get(url, HTTP_X_FORWARDED_FOR="203.0.113.1", **proxy).status_code for _ in range(3)]
        b = api_client.get(url, HTTP_X_FORWARDED_FOR="198.51.100.7", **proxy).status_code
        assert a == [200, 200, 429]
        assert b == 200  # a different client is not affected by the first one's limit
    finally:
        settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK}
        api_settings.reload()
        ScopedRateThrottle.THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES
