import pytest

from apps.assets.models import Asset
from apps.customers.models import Customer
from apps.organizations.catalog import RoleCode

pytestmark = pytest.mark.django_db
URL = "/api/v1/assets/"


@pytest.fixture
def ops(org, make_member):
    return make_member(org, RoleCode.OPS_MANAGER)


@pytest.fixture
def customer(org):
    return Customer.objects.create(organization=org, name="Bank")


def test_create_normalises_tag_and_enforces_uniqueness(client_for, ops, customer):
    client = client_for(ops)
    r = client.post(URL, {"asset_tag": "ast-9", "name": "Generator", "customer": str(customer.id)}, format="json")
    assert r.status_code == 201 and r.json()["asset_tag"] == "AST-9"
    dup = client.post(URL, {"asset_tag": "AST-9", "name": "Other", "customer": str(customer.id)}, format="json")
    assert dup.status_code == 400


def test_validation_rules(client_for, ops, customer):
    client = client_for(ops)
    base = {"asset_tag": "A1", "name": "AC", "customer": str(customer.id)}
    r = client.post(URL, {**base, "installed_at": "2025-01-10", "warranty_expires_at": "2024-01-10"}, format="json")
    assert "warranty_expires_at" in r.json()["error"]["details"]
    r = client.post(URL, {**base, "purchase_cost": "1500.00"}, format="json")
    assert "currency" in r.json()["error"]["details"]
    r = client.post(URL, {**base, "purchase_cost": "1500.50", "currency": "npr"}, format="json")
    assert r.status_code == 201 and r.json()["purchase_cost"] == "1500.50" and r.json()["currency"] == "NPR"


def test_cannot_attach_to_other_tenants_customer(client_for, ops, other_org):
    foreign = Customer.objects.create(organization=other_org, name="Foreign")
    r = client_for(ops).post(URL, {"asset_tag": "A1", "name": "AC", "customer": str(foreign.id)}, format="json")
    assert r.status_code == 400 and "customer" in r.json()["error"]["details"]


def test_assets_with_tickets_cannot_be_deleted(client_for, ops, org, customer):
    from apps.tickets.models import Ticket

    asset = Asset.objects.create(organization=org, customer=customer, asset_tag="A1", name="AC")
    Ticket.objects.create(organization=org, number=1, title="t", description="d", customer=customer, asset=asset)
    assert client_for(ops).delete(f"{URL}{asset.id}/").status_code == 409


def test_warranty_filter(client_for, ops, org, customer):
    from datetime import date, timedelta

    Asset.objects.create(
        organization=org,
        customer=customer,
        asset_tag="A1",
        name="New",
        warranty_expires_at=date.today() + timedelta(days=30),
    )
    Asset.objects.create(
        organization=org,
        customer=customer,
        asset_tag="A2",
        name="Old",
        warranty_expires_at=date.today() - timedelta(days=1),
    )
    names = [a["name"] for a in client_for(ops).get(URL, {"warranty": "active"}).json()["results"]]
    assert names == ["New"]


def test_agents_can_view_but_not_manage(client_for, org, make_member, customer):
    agent = make_member(org, RoleCode.SUPPORT_AGENT)
    assert client_for(agent).get(URL).status_code == 200
    r = client_for(agent).post(URL, {"asset_tag": "A1", "name": "AC", "customer": str(customer.id)}, format="json")
    assert r.status_code == 403
