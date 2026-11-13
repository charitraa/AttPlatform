"""
N+1 guard: list endpoints must use the same number of queries for 5 rows as for 25.

Runs against the full demo dataset (reset_demo), as different roles, so a missing
select_related/prefetch on any list shows up as a growing query count.
"""

import pytest
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User

pytestmark = pytest.mark.django_db

ENDPOINTS = {
    "admin@acme.test": [
        "/api/v1/tickets/", "/api/v1/customers/", "/api/v1/assets/", "/api/v1/work-orders/", "/api/v1/technicians/",
        "/api/v1/notifications/", "/api/v1/users/", "/api/v1/audit-logs/", "/api/v1/ai/recommendations/",
        "/api/v1/knowledge/articles/",
    ],
    "customer@acme.test": ["/api/v1/portal/tickets/"],
    "tech@acme.test": ["/api/v1/work-orders/?technician=me"],
}


def _client(email):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(User.objects.get(email=email)).access_token}")
    return c


def _count(client, url, size):
    sep = "&" if "?" in url else "?"
    with CaptureQueriesContext(connection) as ctx:
        r = client.get(f"{url}{sep}page_size={size}")
    assert r.status_code == 200, (url, r.status_code)
    rows = len(r.json()["results"]) if isinstance(r.json(), dict) and "results" in r.json() else len(r.json())
    return len(ctx.captured_queries), rows


def test_list_queries_do_not_grow_with_rows():
    # Seeded inside this test's transaction, so nothing leaks into other tests.
    call_command("seed_demo", password="Demo!Pass2026")
    call_command("reset_demo", count=45, seed=5)
    problems, report = [], []
    for email, urls in ENDPOINTS.items():
        client = _client(email)
        for url in urls:
            small, small_rows = _count(client, url, 5)
            large, large_rows = _count(client, url, 25)
            who = email.split("@")[0]
            report.append(f"{url} ({who}): {small} → {large} queries for {small_rows} → {large_rows} rows")
            if large != small:
                problems.append(f"{url}: {small} queries for {small_rows} rows but {large} for {large_rows} (N+1)")
            elif large > 25:
                problems.append(f"{url}: {large} queries per page")
    print("\n".join(report))
    assert problems == [], "\n".join(problems)
