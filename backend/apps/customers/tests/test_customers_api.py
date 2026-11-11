import pytest

from apps.customers.models import Customer, CustomerContact
from apps.organizations.catalog import RoleCode

pytestmark = pytest.mark.django_db
URL = "/api/v1/customers/"


@pytest.fixture
def agent(org, make_member):
    return make_member(org, RoleCode.SUPPORT_AGENT)


def test_crud_scoped_and_audited(client_for, agent, other_org):
    client = client_for(agent)
    r = client.post(URL, {"name": "Himalayan Bank", "tier": "enterprise", "country": "np"}, format="json")
    assert r.status_code == 201
    body = r.json()
    assert body["country"] == "NP"
    assert body["open_ticket_count"] == 0 and body["asset_count"] == 0
    Customer.objects.create(organization=other_org, name="Hidden Co")
    names = [c["name"] for c in client.get(URL).json()["results"]]
    assert names == ["Himalayan Bank"]
    assert client.patch(f"{URL}{body['id']}/", {"phone": "+977-1-5550000"}, format="json").json()["phone"]


def test_duplicate_active_name_rejected_case_insensitively(client_for, agent):
    client = client_for(agent)
    client.post(URL, {"name": "Everest Hotel"}, format="json")
    r = client.post(URL, {"name": "everest hotel"}, format="json")
    assert r.status_code == 400 and "name" in r.json()["error"]["details"]


def test_delete_archives_and_restore(client_for, agent):
    client = client_for(agent)
    cid = client.post(URL, {"name": "Old Co"}, format="json").json()["id"]
    assert client.delete(f"{URL}{cid}/").status_code == 204
    assert Customer.objects.filter(pk=cid).exists()
    assert client.get(URL).json()["count"] == 0
    assert client.get(URL, {"archived": "true"}).json()["count"] == 1
    assert client.post(f"{URL}{cid}/restore/").json()["archived_at"] is None


def test_technicians_can_view_but_not_manage(client_for, org, make_member):
    tech = make_member(org, RoleCode.FIELD_TECHNICIAN)
    client = client_for(tech)
    assert client.get(URL).status_code == 200
    assert client.post(URL, {"name": "X"}, format="json").status_code == 403


def test_customer_role_cannot_list_customers(client_for, org, make_member):
    assert client_for(make_member(org, RoleCode.CUSTOMER)).get(URL).status_code == 403


def test_contacts_single_primary_and_isolation(client_for, agent, other_org, make_member):
    client = client_for(agent)
    cid = client.post(URL, {"name": "Bank"}, format="json").json()["id"]
    contacts = f"{URL}{cid}/contacts/"
    a = client.post(contacts, {"name": "Asha", "is_primary": True}, format="json").json()
    b = client.post(contacts, {"name": "Bikash", "is_primary": True}, format="json").json()
    assert CustomerContact.objects.get(pk=a["id"]).is_primary is False
    assert CustomerContact.objects.get(pk=b["id"]).is_primary is True
    assert client.get(URL).json()["results"][0]["primary_contact"]["name"] == "Bikash"

    outsider = make_member(other_org, RoleCode.ORG_ADMIN)
    assert client_for(outsider).get(contacts).status_code == 404
