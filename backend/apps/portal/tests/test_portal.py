import pytest

from apps.assets.models import Asset
from apps.customers.models import Customer
from apps.field_service.models import WorkOrder
from apps.organizations.catalog import RoleCode
from apps.portal.models import CustomerFeedback
from apps.tickets.models import Ticket, TicketCategory

pytestmark = pytest.mark.django_db
URL = "/api/v1/portal/tickets/"


@pytest.fixture
def world(org, make_member):
    bank = Customer.objects.create(organization=org, name="Himalayan Bank")
    hotel = Customer.objects.create(organization=org, name="Everest Hotel")
    cust = make_member(org, RoleCode.CUSTOMER, email="sita@bank.test")
    bank.contacts.create(name="Sita Rai", email="sita@bank.test", user=cust.user)
    agent = make_member(org, RoleCode.SUPPORT_AGENT, email="ana@acme.test")
    agent.user.first_name, agent.user.last_name = "Ana", "Agent"
    agent.user.save()
    return {
        "bank": bank, "hotel": hotel, "customer": cust, "agent": agent,
        "category": TicketCategory.objects.create(organization=org, name="Printers"),
        "atm": Asset.objects.create(organization=org, customer=bank, name="ATM 4", asset_tag="ATM-4"),
        "minibar": Asset.objects.create(organization=org, customer=hotel, name="Minibar", asset_tag="MB-1"),
    }


def make_ticket(org, customer, **kw):
    return Ticket.objects.create(organization=org, number=Ticket.objects.count() + 1, title=kw.pop("title", "Issue"),
                                 description="d", customer=customer, **kw)


def test_customers_raise_tickets_for_their_own_account(client_for, world):
    c = client_for(world["customer"])
    opts = c.get("/api/v1/portal/options/").json()
    assert [a["name"] for a in opts["assets"]] == ["ATM 4"]  # not the hotel's minibar
    r = c.post(URL, {"title": "Card stuck", "description": "ATM 4 kept my card", "category": str(world["category"].id),
                     "asset": str(world["atm"].id)}, format="json")
    assert r.status_code == 201, r.json()
    t = Ticket.objects.get(pk=r.json()["id"])
    assert (t.customer, t.channel, t.contact.email, t.asset) == (world["bank"], "portal", "sita@bank.test", world["atm"])
    assert r.json()["status_label"] == "Received"
    foreign = c.post(URL, {"title": "x", "description": "y", "asset": str(world["minibar"].id)}, format="json")
    assert foreign.status_code == 404


def test_portal_shows_only_own_tickets_and_no_internal_data(client_for, world, org):
    mine = make_ticket(org, world["bank"], assigned_agent=world["agent"].user, tags=["vip"])
    make_ticket(org, world["hotel"], title="Hotel's ticket")
    c = client_for(world["customer"])
    listed = c.get(URL).json()["results"]
    assert [t["id"] for t in listed] == [str(mine.id)]
    detail = c.get(f"{URL}{mine.id}/").json()
    assert detail["handled_by"] == "Ana"  # first name only
    for hidden in ("tags", "due_at", "sla", "priority_source", "assigned_agent", "internal_notes"):
        assert hidden not in detail
    assert b"ana@acme.test" not in c.get(f"{URL}{mine.id}/").content
    other = Ticket.objects.get(title="Hotel's ticket")
    assert c.get(f"{URL}{other.id}/").status_code == 404


def test_conversation_hides_internal_notes(client_for, world, org):
    t = make_ticket(org, world["bank"])
    staff = client_for(world["agent"])
    staff.post(f"/api/v1/tickets/{t.id}/comments/", {"body": "Customer is difficult", "visibility": "internal"},
               format="json")
    staff.post(f"/api/v1/tickets/{t.id}/comments/", {"body": "Technician on the way", "visibility": "public"},
               format="json")
    c = client_for(world["customer"])
    thread = c.post(f"{URL}{t.id}/comments/", {"body": "Thanks!"}, format="json").json()
    assert [(m["body"], m["from_support"]) for m in thread] == [("Technician on the way", True), ("Thanks!", False)]
    assert thread[0]["author"] == "Ana"


def test_confirm_reopen_and_rate(client_for, world, org):
    t = make_ticket(org, world["bank"], status="resolved", resolution_notes="Replaced the card reader")
    c = client_for(world["customer"])
    actions = c.get(f"{URL}{t.id}/").json()["actions"]
    assert actions == {"reply": True, "confirm": True, "reopen": True, "rate": True}
    assert c.post(f"{URL}{t.id}/reopen/", {}, format="json").status_code == 400  # needs a reason
    r = c.post(f"{URL}{t.id}/reopen/", {"note": "It's jammed again"}, format="json")
    assert r.json()["status"] == "reopened" and r.json()["status_label"] == "In progress"
    Ticket.objects.filter(pk=t.pk).update(status="resolved")
    assert c.post(f"{URL}{t.id}/confirm/").json()["status"] == "closed"

    fb = c.post("/api/v1/portal/feedback/", {"ticket": str(t.id), "rating": 5, "comment": "Quick fix"}, format="json")
    assert fb.status_code == 201
    assert c.post("/api/v1/portal/feedback/", {"ticket": str(t.id), "rating": 1}, format="json").status_code == 409
    after = c.get(f"{URL}{t.id}/").json()
    assert after["feedback"]["rating"] == 5 and after["actions"]["rate"] is False


def test_feedback_rules(client_for, world, org):
    c = client_for(world["customer"])
    open_ticket = make_ticket(org, world["bank"])
    assert c.post("/api/v1/portal/feedback/", {"ticket": str(open_ticket.id), "rating": 4},
                  format="json").status_code == 400
    hotel_ticket = make_ticket(org, world["hotel"], status="closed")
    assert c.post("/api/v1/portal/feedback/", {"ticket": str(hotel_ticket.id), "rating": 4},
                  format="json").status_code == 404
    wo = WorkOrder.objects.create(organization=org, number=1, customer=world["bank"], title="Fix ATM",
                                  status="completed")
    r = c.post("/api/v1/portal/feedback/", {"work_order": str(wo.id), "rating": 2, "comment": "Late"}, format="json")
    assert r.status_code == 201 and CustomerFeedback.objects.get().customer == world["bank"]
    assert c.post("/api/v1/portal/feedback/", {"rating": 3}, format="json").status_code == 400  # needs a subject
    assert c.post("/api/v1/portal/feedback/", {"ticket": str(open_ticket.id), "work_order": str(wo.id), "rating": 3},
                  format="json").status_code == 400


def test_portal_is_for_customers_only(client_for, world):
    assert client_for(world["agent"]).get(URL).status_code == 403
