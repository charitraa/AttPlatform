import pytest

from apps.assets.models import Asset
from apps.customers.models import Customer, CustomerContact
from apps.organizations.catalog import RoleCode
from apps.tickets.models import TicketCategory


@pytest.fixture
def customer(org):
    return Customer.objects.create(organization=org, name="Himalayan Bank")


@pytest.fixture
def other_customer(org):
    return Customer.objects.create(organization=org, name="Everest Hotel")


@pytest.fixture
def contact(customer):
    return CustomerContact.objects.create(customer=customer, name="Hari", email="hari@bank.test", is_primary=True)


@pytest.fixture
def asset(org, customer):
    return Asset.objects.create(organization=org, customer=customer, asset_tag="AST-1", name="Rooftop AC")


@pytest.fixture
def category(org):
    return TicketCategory.objects.create(organization=org, name="HVAC", default_priority="high")


@pytest.fixture
def agent(org, make_member):
    return make_member(org, RoleCode.SUPPORT_AGENT, email="agent@acme.test")


@pytest.fixture
def tech(org, make_member):
    return make_member(org, RoleCode.FIELD_TECHNICIAN, email="tech@acme.test")


@pytest.fixture
def portal_user(org, make_member, customer):
    """A customer-portal user linked to `customer` through a contact."""
    member = make_member(org, RoleCode.CUSTOMER, email="it@bank.test")
    CustomerContact.objects.create(customer=customer, user=member.user, name="Bank IT", email="it@bank.test")
    return member


@pytest.fixture
def create_ticket(client_for, agent, customer):
    """Create a ticket through the API as `agent` (or `as_member`)."""

    def _create(as_member=None, **overrides):
        payload = {
            "title": "AC not cooling",
            "description": "Server room is 31°C.",
            "customer": str(customer.id),
            **overrides,
        }
        response = client_for(as_member or agent).post("/api/v1/tickets/", payload, format="json")
        assert response.status_code == 201, response.json()
        return response.json()

    return _create
