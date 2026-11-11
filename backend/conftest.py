import itertools

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.organizations.catalog import RoleCode
from apps.organizations.models import Membership, Organization
from apps.organizations.services import get_system_role

PASSWORD = "Correct-Horse-42!"
_seq = itertools.count(1)


@pytest.fixture(autouse=True)
def _clear_cache():
    # Throttle counters live in the cache; isolate tests from each other.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def make_org(db):
    def _make(name: str | None = None) -> Organization:
        n = next(_seq)
        return Organization.objects.create(name=name or f"Org {n}", slug=f"org-{n}")

    return _make


@pytest.fixture
def make_member(db, django_user_model):
    def _make(org: Organization, role: str = RoleCode.SUPPORT_AGENT, *, email: str | None = None,
              is_active: bool = True, password: str = PASSWORD) -> Membership:
        user = django_user_model.objects.filter(email=email).first() if email else None
        if user is None:
            user = django_user_model.objects.create_user(
                email=email or f"user{next(_seq)}@example.test", password=password, first_name="Test", last_name=role
            )
        return Membership.objects.create(user=user, organization=org, role=get_system_role(role), is_active=is_active)

    return _make


@pytest.fixture
def org(make_org) -> Organization:
    return make_org("Acme")


@pytest.fixture
def other_org(make_org) -> Organization:
    return make_org("Globex")


@pytest.fixture
def admin(org, make_member) -> Membership:
    return make_member(org, RoleCode.ORG_ADMIN, email="admin@acme.test")


@pytest.fixture
def client_for():
    """APIClient authenticated with a real JWT access token for the membership's user."""

    def _client(membership: Membership, org_slug: str | None = None) -> APIClient:
        client = APIClient()
        token = RefreshToken.for_user(membership.user).access_token
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        if org_slug:
            headers["HTTP_X_ORGANIZATION"] = org_slug
        client.credentials(**headers)
        return client

    return _client
