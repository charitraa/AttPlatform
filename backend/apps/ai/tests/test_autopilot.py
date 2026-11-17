"""The AI autopilot: a customer request handled end to end by AI, each step behind its own switch."""

import pytest

from apps.ai.models import AIRecommendation
from apps.customers.models import Customer
from apps.field_service.models import Skill, Technician, TechnicianSkill, WorkOrder
from apps.notifications.models import Notification
from apps.organizations.catalog import RoleCode
from apps.tickets.models import Ticket, TicketAssignment, TicketCategory, TicketComment, TicketHistory

pytestmark = pytest.mark.django_db
ALL_ON = {"ai_auto_triage": True, "routing_policy": "auto", "ai_auto_reply": True, "ai_auto_dispatch": True}


@pytest.fixture
def world(org, make_member, settings):
    settings.AI_PROVIDER = "mock"
    settings.AI_FALLBACKS = []
    settings.AI_AUTO_APPLY_MIN_CONFIDENCE = 0.3  # the offline mock never claims more than 0.75
    bank = Customer.objects.create(organization=org, name="Annapurna Cold Storage", city="Chitwan")
    cust = make_member(org, RoleCode.CUSTOMER, email="sita@cold.test")
    bank.contacts.create(name="Sita", email="sita@cold.test", user=cust.user)
    refrigeration = TicketCategory.objects.create(organization=org, name="Refrigeration", default_priority="medium")
    TicketCategory.objects.create(organization=org, name="Printers")
    skill = Skill.objects.create(organization=org, name="Refrigeration")
    skill.ticket_categories.add(refrigeration)
    tech_m = make_member(org, RoleCode.FIELD_TECHNICIAN, email="tariq@acme.test")
    TechnicianSkill.objects.create(technician=Technician.objects.get(user=tech_m.user), skill=skill, level=5)
    return {
        "customer": cust,
        "tech": tech_m,
        "category": refrigeration,
        "agent": make_member(org, RoleCode.SUPPORT_AGENT, email="ana@acme.test"),
        "admin": make_member(org, RoleCode.ORG_ADMIN, email="admin@acme.test"),
    }


def raise_ticket(client_for, member, run, **body):
    with run(execute=True):
        r = client_for(member).post(
            "/api/v1/portal/tickets/",
            {
                "title": "Refrigeration failure: cold room critical",
                "description": "The refrigeration unit stopped, the cold room is at 9C and stock is at risk. Urgent.",
                **body,
            },
            format="json",
        )
    assert r.status_code == 201, r.json()
    return Ticket.objects.get(pk=r.json()["id"])


def test_full_autopilot_handles_a_customer_request(org, world, client_for, django_capture_on_commit_callbacks):
    org.settings = {**(org.settings or {}), **ALL_ON}
    org.save()
    t = raise_ticket(client_for, world["customer"], django_capture_on_commit_callbacks)
    t.refresh_from_db()

    # 1. Category and priority set by AI (labelled in history).
    assert t.category == world["category"]
    assert TicketHistory.objects.filter(ticket=t, field="category", actor_type="ai").exists()
    assert AIRecommendation.objects.filter(ticket=t, type="category", status="auto_applied").exists()
    # 2. Agent assigned by AI and notified.
    assert t.assigned_agent is not None
    assert TicketAssignment.objects.filter(ticket=t, role="agent", source="ai_auto").exists()
    assert Notification.objects.filter(recipient=t.assigned_agent, type="ticket_assigned").exists()
    # 3. The customer got a labelled AI reply, which doesn't count as the SLA first response.
    reply = TicketComment.objects.get(ticket=t, source="ai_auto")
    assert reply.visibility == "public" and reply.author is None and "automated assistant" in reply.body
    assert t.first_response_at is None
    thread = client_for(world["customer"]).get(f"/api/v1/portal/tickets/{t.id}/comments/").json()
    assert thread[0]["from_support"] is True
    # 4. A work order was created and assigned to the skilled technician, who is notified.
    wo = WorkOrder.objects.get(ticket=t)
    assert wo.technician.user == world["tech"].user and wo.created_by is None and wo.status == "assigned"
    assert wo.status_log.filter(note__icontains="AI").exists()
    assert Notification.objects.filter(recipient=world["tech"].user, type="work_order_assigned").exists()


def test_each_switch_works_on_its_own(org, world, client_for, django_capture_on_commit_callbacks):
    org.settings = {**(org.settings or {}), "ai_auto_reply": True}  # only the reply
    org.save()
    t = raise_ticket(client_for, world["customer"], django_capture_on_commit_callbacks)
    t.refresh_from_db()
    assert TicketComment.objects.filter(ticket=t, source="ai_auto").exists()
    assert t.assigned_agent is None and not WorkOrder.objects.filter(ticket=t).exists()
    assert AIRecommendation.objects.filter(ticket=t, type="category", status="pending").exists()  # suggested only


def test_no_reply_to_staff_tickets_and_no_second_reply(org, world, client_for, django_capture_on_commit_callbacks):
    from apps.ai.services import run_autopilot

    org.settings = {**(org.settings or {}), "ai_auto_reply": True}
    org.save()
    with django_capture_on_commit_callbacks(execute=True):
        r = client_for(world["agent"]).post(
            "/api/v1/tickets/",
            {"title": "Refrigeration check", "description": "Routine", "customer": str(Customer.objects.get().id)},
            format="json",
        )
    staff_ticket = Ticket.objects.get(pk=r.json()["id"])
    assert not TicketComment.objects.filter(ticket=staff_ticket, source="ai_auto").exists()

    t = raise_ticket(client_for, world["customer"], django_capture_on_commit_callbacks)
    assert run_autopilot(t)["reply"] == "skipped: already answered"
    assert TicketComment.objects.filter(ticket=t, source="ai_auto").count() == 1


def test_dispatch_skips_when_nobody_is_suitable(org, world, client_for, django_capture_on_commit_callbacks):
    org.settings = {**(org.settings or {}), **ALL_ON}
    org.save()
    Technician.objects.update(status="on_leave")
    t = raise_ticket(client_for, world["customer"], django_capture_on_commit_callbacks)
    assert not WorkOrder.objects.filter(ticket=t).exists()
    t.refresh_from_db()
    assert t.category == world["category"] and t.assigned_agent is not None  # the other steps still ran


def test_switches_are_saved_through_the_settings_api(org, world, client_for):
    admin = client_for(world["admin"])
    r = admin.patch(
        "/api/v1/organization/", {"settings": {"ai_auto_reply": True, "ai_auto_dispatch": True}}, format="json"
    )
    assert r.status_code == 200, r.json()
    assert r.json()["settings"]["ai_auto_reply"] is True and r.json()["settings"]["ai_auto_dispatch"] is True


def test_reply_only_states_what_was_actually_done(org, world, client_for, django_capture_on_commit_callbacks):
    from apps.ai.models import AIAnalysis
    from apps.ai.prompts import build_prompt

    org.settings = {**(org.settings or {}), **ALL_ON}
    org.save()
    t = raise_ticket(client_for, world["customer"], django_capture_on_commit_callbacks)
    reply = AIAnalysis.objects.get(ticket=t, kind="response_suggestion")
    facts = reply.input["actions_taken"]
    assert any(f.startswith("Technician ") and "assigned to visit" in f for f in facts)  # dispatch ran first
    prompt = build_prompt("response_suggestion", {"title": "x", "description": "y", "actions_taken": facts})
    assert "<actions_taken>" in prompt and "assigned to visit" in prompt

    # Nothing dispatched or assigned: the reply is told so (empty facts apart from priority).
    org.settings = {**org.settings, "ai_auto_dispatch": False, "routing_policy": "recommend"}
    org.save()
    t2 = raise_ticket(client_for, world["customer"], django_capture_on_commit_callbacks)
    facts2 = AIAnalysis.objects.get(ticket=t2, kind="response_suggestion").input["actions_taken"]
    assert not any("Technician" in f or "assigned to" in f for f in facts2)


def test_meta_notes_about_sources_are_not_sent_to_customers():
    from apps.ai.services import _strip_meta_notes

    draft = (
        "Hi Cara,\n\nA technician is on the way.\n\nBest regards,\nSupport Team\n\n"
        "(No knowledge articles were referenced for this reply.)"
    )
    assert _strip_meta_notes(draft) == "Hi Cara,\n\nA technician is on the way.\n\nBest regards,\nSupport Team"
    assert _strip_meta_notes("Sources: KB-12, KB-40\nHello") == "Hello"
    assert _strip_meta_notes("Best regards,\n[Support Agent]") == "Best regards,"
    for keep in ("Our knowledge article on defrosting explains the steps below.", "Please keep the door closed."):
        assert _strip_meta_notes(keep) == keep
