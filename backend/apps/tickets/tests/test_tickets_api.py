import pytest

from apps.audit.models import AuditLog
from apps.core import events
from apps.organizations.catalog import RoleCode
from apps.tickets.models import Ticket, TicketAssignment, TicketHistory

pytestmark = pytest.mark.django_db
URL = "/api/v1/tickets/"


def url(ticket_id, suffix=""):
    return f"{URL}{ticket_id}/{suffix}"


# ------------------------------------------------------------------------ create
def test_create_assigns_sequential_reference_and_records_history(create_ticket, category, contact, asset):
    first = create_ticket(category=str(category.id), contact=str(contact.id), asset=str(asset.id), priority="critical")
    second = create_ticket()
    assert first["reference"] == "TCK-000001"
    assert second["reference"] == "TCK-000002"
    assert first["status"] == "new"
    assert first["priority"] == "critical"
    assert first["priority_source"] == "manual"
    assert first["contact"]["name"] == "Hari"
    assert TicketHistory.objects.filter(ticket_id=first["id"], event="created").exists()
    assert AuditLog.objects.filter(action="ticket.created", target_id=first["id"]).exists()


def test_numbers_are_per_organization(create_ticket, client_for, other_org, make_member):
    from apps.customers.models import Customer

    create_ticket()
    other_agent = make_member(other_org, RoleCode.SUPPORT_AGENT)
    other_customer = Customer.objects.create(organization=other_org, name="Globex Client")
    response = client_for(other_agent).post(
        URL, {"title": "x", "description": "y", "customer": str(other_customer.id)}, format="json"
    )
    assert response.json()["reference"] == "TCK-000001"


def test_create_publishes_event_after_commit(create_ticket, django_capture_on_commit_callbacks):
    received = []
    events.subscribe("ticket.created")(received.append)
    try:
        create_ticket()
    finally:
        events._handlers["ticket.created"].remove((received.append, False))
    assert len(received) == 1
    assert received[0].payload["ticket_id"]


def test_category_default_priority_applies_when_not_given(create_ticket, category):
    ticket = create_ticket(category=str(category.id))
    assert ticket["priority"] == "high"
    assert ticket["priority_source"] == "policy"


def test_create_rejects_mismatched_relations(client_for, agent, customer, other_customer, contact, asset):
    client = client_for(agent)
    base = {"title": "t", "description": "d", "customer": str(other_customer.id)}
    r = client.post(URL, {**base, "contact": str(contact.id)}, format="json")
    assert r.status_code == 400 and "contact" in r.json()["error"]["details"]
    r = client.post(URL, {**base, "asset": str(asset.id)}, format="json")
    assert r.status_code == 400 and "asset" in r.json()["error"]["details"]


def test_create_cannot_reference_another_tenants_customer(client_for, agent, other_org):
    from apps.customers.models import Customer

    foreign = Customer.objects.create(organization=other_org, name="Foreign")
    r = client_for(agent).post(URL, {"title": "t", "description": "d", "customer": str(foreign.id)}, format="json")
    assert r.status_code == 400
    assert "customer" in r.json()["error"]["details"]


def test_portal_user_creates_for_own_account_without_setting_priority(create_ticket, portal_user, customer, category):
    ticket = create_ticket(as_member=portal_user, priority="critical", category=str(category.id))
    assert ticket["priority"] == "high"  # category default; customers can't choose priority
    assert ticket["channel"] == "portal"
    assert ticket["contact"]["name"] == "Bank IT"


def test_portal_user_cannot_raise_for_another_customer(client_for, portal_user, other_customer):
    r = client_for(portal_user).post(
        URL, {"title": "t", "description": "d", "customer": str(other_customer.id)}, format="json"
    )
    assert r.status_code == 403


def test_technician_cannot_create(client_for, tech, customer):
    r = client_for(tech).post(URL, {"title": "t", "description": "d", "customer": str(customer.id)}, format="json")
    assert r.status_code == 403


# ---------------------------------------------------------------- visibility
def test_visibility_rules_by_role(create_ticket, client_for, agent, tech, portal_user, other_customer, admin):
    mine = create_ticket()  # customer = portal user's account
    other = create_ticket(customer=str(other_customer.id))
    client_for(admin).post(url(other["id"], "assign/"), {"technician": str(tech.user.id)}, format="json")

    def ids(member):
        return {t["id"] for t in client_for(member).get(URL).json()["results"]}

    assert ids(agent) == {mine["id"], other["id"]}
    assert ids(tech) == {other["id"]}  # only assigned to them
    assert ids(portal_user) == {mine["id"]}  # only their customer account
    assert client_for(portal_user).get(url(other["id"])).status_code == 404
    assert client_for(tech).get(url(mine["id"])).status_code == 404


def test_other_organization_cannot_see_tickets(create_ticket, client_for, other_org, make_member):
    ticket = create_ticket()
    outsider = make_member(other_org, RoleCode.ORG_ADMIN)
    client = client_for(outsider)
    assert client.get(URL).json()["count"] == 0
    assert client.get(url(ticket["id"])).status_code == 404
    assert client.post(url(ticket["id"], "comments/"), {"body": "hi"}, format="json").status_code == 404


# ------------------------------------------------------------- filters/search
def test_filters_search_and_priority_ordering(create_ticket, client_for, agent, admin, other_customer):
    low = create_ticket(title="Printer jam", priority="low")
    crit = create_ticket(title="Generator failure", description="Backup generator will not start", priority="critical")
    high = create_ticket(title="Wi-Fi slow", priority="high", customer=str(other_customer.id))
    client = client_for(agent)

    def refs(**params):
        return [t["reference"] for t in client.get(URL, params).json()["results"]]

    assert refs(priority="high,critical", ordering="-priority") == [crit["reference"], high["reference"]]
    assert refs(ordering="priority")[0] == low["reference"]
    assert refs(search="generator") == [crit["reference"]]  # full-text on description
    assert refs(search="TCK-000001") == [low["reference"]]
    assert refs(search="3") == [high["reference"]]
    assert refs(customer=str(other_customer.id)) == [high["reference"]]
    assert set(refs(assigned_agent="none")) == {low["reference"], crit["reference"], high["reference"]}
    assert (
        client_for(admin).post(url(low["id"], "assign/"), {"agent": str(agent.user.id)}, format="json").status_code
        == 200
    )
    assert refs(assigned_agent="me") == [low["reference"]]
    assert set(refs(status="active")) == {low["reference"], crit["reference"], high["reference"]}


# ----------------------------------------------------------------------- update
def test_update_records_field_history_and_marks_priority_manual(create_ticket, client_for, agent, category):
    ticket = create_ticket(category=str(category.id))
    r = client_for(agent).patch(
        url(ticket["id"]), {"priority": "low", "title": "AC fixed?", "tags": ["Urgent", " hvac "]}, format="json"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["priority"] == "low" and body["priority_source"] == "manual"
    assert body["tags"] == ["hvac", "urgent"]
    fields = set(
        TicketHistory.objects.filter(ticket_id=ticket["id"], event="field_changed").values_list("field", flat=True)
    )
    assert fields == {"priority", "title", "tags"}


def test_customers_and_technicians_cannot_edit(create_ticket, client_for, portal_user, tech):
    ticket = create_ticket()
    assert client_for(portal_user).patch(url(ticket["id"]), {"title": "x"}, format="json").status_code == 403
    assert client_for(tech).patch(url(ticket["id"]), {"title": "x"}, format="json").status_code == 403


# ------------------------------------------------------------------ transitions
def test_state_machine_and_resolution_rules(create_ticket, client_for, agent):
    ticket = create_ticket()
    client = client_for(agent)
    r = client.post(url(ticket["id"], "transition/"), {"status": "closed_wrong"}, format="json")
    assert r.status_code == 400
    r = client.post(url(ticket["id"], "transition/"), {"status": "pending_parts"}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_transition"

    assert client.post(url(ticket["id"], "transition/"), {"status": "in_progress"}, format="json").status_code == 200
    r = client.post(url(ticket["id"], "transition/"), {"status": "resolved"}, format="json")
    assert r.status_code == 400 and "resolution_notes" in r.json()["error"]["details"]
    r = client.post(
        url(ticket["id"], "transition/"),
        {"status": "resolved", "resolution_notes": "Replaced capacitor."},
        format="json",
    )
    body = r.json()
    assert body["status"] == "resolved" and body["resolved_at"] and body["resolution_notes"] == "Replaced capacitor."
    assert body["allowed_transitions"] == ["closed", "reopened"]

    r = client.post(url(ticket["id"], "transition/"), {"status": "reopened", "note": "Still warm."}, format="json")
    assert r.json()["resolved_at"] is None
    note = client.get(url(ticket["id"], "comments/")).json()[-1]
    assert note["body"] == "Still warm." and note["visibility"] == "internal"


def test_customer_can_only_confirm_or_reopen_resolution(create_ticket, client_for, agent, portal_user):
    ticket = create_ticket()
    staff, cust = client_for(agent), client_for(portal_user)
    assert cust.get(url(ticket["id"])).json()["allowed_transitions"] == []
    assert cust.post(url(ticket["id"], "transition/"), {"status": "in_progress"}, format="json").status_code == 400
    staff.post(url(ticket["id"], "transition/"), {"status": "resolved", "resolution_notes": "Fixed."}, format="json")
    r = cust.post(url(ticket["id"], "transition/"), {"status": "closed"}, format="json")
    assert r.status_code == 200
    assert r.json()["status"] == "closed" and r.json()["customer_confirmed_at"]


def test_escalation_requires_reason(create_ticket, client_for, agent):
    ticket = create_ticket()
    client = client_for(agent)
    assert client.post(url(ticket["id"], "escalate/"), {"reason": ""}, format="json").status_code == 400
    r = client.post(url(ticket["id"], "escalate/"), {"reason": "Vendor needed"}, format="json")
    assert r.json()["status"] == "escalated"


# ------------------------------------------------------------------- assignment
def test_assignment_tracks_history_and_auto_moves_to_assigned(
    create_ticket, client_for, admin, agent, tech, make_member
):
    ticket = create_ticket()
    client = client_for(admin)
    r = client.post(
        url(ticket["id"], "assign/"), {"agent": str(agent.user.id), "technician": str(tech.user.id)}, format="json"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "assigned"
    assert body["assigned_agent"]["email"] == "agent@acme.test"
    assert body["assigned_technician"]["email"] == "tech@acme.test"

    other_agent = make_member(admin.organization, RoleCode.SUPPORT_AGENT)
    client.post(url(ticket["id"], "assign/"), {"agent": str(other_agent.user.id)}, format="json")
    rows = TicketAssignment.objects.filter(ticket_id=ticket["id"], role="agent").order_by("assigned_at")
    assert [r.assignee_id for r in rows] == [agent.user.id, other_agent.user.id]
    assert rows[0].unassigned_at is not None and rows[1].unassigned_at is None
    # technician untouched because it was omitted
    assert client.get(url(ticket["id"])).json()["assigned_technician"]["email"] == "tech@acme.test"

    r = client.post(url(ticket["id"], "assign/"), {"technician": None}, format="json")
    assert r.json()["assigned_technician"] is None


def test_assignment_validates_role_and_organization(
    create_ticket, client_for, admin, agent, tech, other_org, make_member
):
    ticket = create_ticket()
    client = client_for(admin)
    assert (
        client.post(url(ticket["id"], "assign/"), {"technician": str(agent.user.id)}, format="json").status_code == 400
    )
    assert client.post(url(ticket["id"], "assign/"), {"agent": str(tech.user.id)}, format="json").status_code == 400
    outsider = make_member(other_org, RoleCode.SUPPORT_AGENT)
    assert client.post(url(ticket["id"], "assign/"), {"agent": str(outsider.user.id)}, format="json").status_code == 400


def test_agents_without_assign_permission_cannot_assign(create_ticket, client_for, agent):
    ticket = create_ticket()
    r = client_for(agent).post(url(ticket["id"], "assign/"), {"agent": str(agent.user.id)}, format="json")
    assert r.status_code == 403  # support agents lack tickets.assign


# --------------------------------------------------------------------- comments
def test_internal_notes_are_hidden_from_customers(create_ticket, client_for, agent, portal_user):
    ticket = create_ticket()
    staff, cust = client_for(agent), client_for(portal_user)
    staff.post(url(ticket["id"], "comments/"), {"body": "Customer is VIP", "visibility": "internal"}, format="json")
    staff.post(url(ticket["id"], "comments/"), {"body": "We're on it"}, format="json")

    assert [c["body"] for c in cust.get(url(ticket["id"], "comments/")).json()] == ["We're on it"]
    assert len(staff.get(url(ticket["id"], "comments/")).json()) == 2
    assert all(not h["internal"] for h in cust.get(url(ticket["id"], "history/")).json())
    r = cust.post(url(ticket["id"], "comments/"), {"body": "secret", "visibility": "internal"}, format="json")
    assert r.status_code == 403


def test_first_public_staff_reply_sets_first_response(create_ticket, client_for, agent):
    ticket = create_ticket()
    client = client_for(agent)
    client.post(url(ticket["id"], "comments/"), {"body": "note", "visibility": "internal"}, format="json")
    assert client.get(url(ticket["id"])).json()["first_response_at"] is None
    client.post(url(ticket["id"], "comments/"), {"body": "Hello"}, format="json")
    assert client.get(url(ticket["id"])).json()["first_response_at"] is not None


def test_customer_reply_moves_pending_customer_back_to_team(create_ticket, client_for, agent, portal_user):
    ticket = create_ticket()
    client_for(agent).post(url(ticket["id"], "transition/"), {"status": "pending_customer"}, format="json")
    client_for(portal_user).post(url(ticket["id"], "comments/"), {"body": "Here are the details"}, format="json")
    assert Ticket.objects.get(pk=ticket["id"]).status == "open"


# --------------------------------------------------------------------- archiving
def test_archived_tickets_are_hidden_and_frozen(create_ticket, client_for, admin):
    ticket = create_ticket()
    client = client_for(admin)
    assert client.post(url(ticket["id"], "archive/")).json()["archived_at"]
    assert client.get(URL).json()["count"] == 0
    assert client.get(url(ticket["id"])).status_code == 200  # still reachable directly
    assert client.get(URL, {"archived": "true"}).json()["count"] == 1
    r = client.patch(url(ticket["id"]), {"title": "x"}, format="json")
    assert r.status_code == 400
    assert client.post(url(ticket["id"], "unarchive/")).json()["archived_at"] is None


def test_agents_cannot_archive(create_ticket, client_for, agent):
    ticket = create_ticket()
    assert client_for(agent).post(url(ticket["id"], "archive/")).status_code == 403


# -------------------------------------------------------------------- categories
def test_categories_readable_by_members_managed_by_admins(client_for, admin, agent, portal_user, category):
    assert client_for(portal_user).get("/api/v1/ticket-categories/").json()[0]["name"] == "HVAC"
    assert client_for(agent).post("/api/v1/ticket-categories/", {"name": "Plumbing"}, format="json").status_code == 403
    client = client_for(admin)
    assert client.post("/api/v1/ticket-categories/", {"name": "Plumbing"}, format="json").status_code == 201
    dup = client.post("/api/v1/ticket-categories/", {"name": "hvac"}, format="json")
    assert dup.status_code == 400


def test_portal_user_customer_is_resolved_automatically(client_for, portal_user, customer):
    r = client_for(portal_user).post(URL, {"title": "Printer", "description": "Jammed"}, format="json")
    assert r.status_code == 201
    assert r.json()["customer"]["id"] == str(customer.id)


def test_staff_must_choose_customer(client_for, agent):
    r = client_for(agent).post(URL, {"title": "t", "description": "d"}, format="json")
    assert r.status_code == 400 and "customer" in r.json()["error"]["details"]
