import pytest

from apps.ai.models import AIAnalysis, AIInsight, AIRecommendation
from apps.customers.models import Customer, CustomerContact
from apps.knowledge.models import KnowledgeArticle
from apps.organizations.catalog import RoleCode
from apps.tickets.models import Ticket, TicketAssignment, TicketCategory, TicketHistory

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(org, make_member):
    customer = Customer.objects.create(organization=org, name="Himalayan Bank", tier="enterprise")
    hvac = TicketCategory.objects.create(
        organization=org, name="HVAC", department="Facilities", description="cooling air conditioning"
    )
    TicketCategory.objects.create(organization=org, name="Printers", department="IT", description="printer jam")
    return {
        "customer": customer,
        "hvac": hvac,
        "ops": make_member(org, RoleCode.OPS_MANAGER, email="ops@acme.test"),
        "agent": make_member(org, RoleCode.SUPPORT_AGENT, email="agent@acme.test"),
    }


@pytest.fixture
def new_ticket(client_for, setup, django_capture_on_commit_callbacks):
    """Create a ticket via the API with on-commit callbacks executed (so AI triage runs, eagerly)."""

    def _create(
        title="HVAC unit not cooling",
        description="The air conditioning blows warm air. Server room outage.",
        as_member=None,
        **extra,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            r = client_for(as_member or setup["ops"]).post(
                "/api/v1/tickets/",
                {"title": title, "description": description, "customer": str(setup["customer"].id), **extra},
                format="json",
            )
        assert r.status_code == 201, r.json()
        return Ticket.objects.get(pk=r.json()["id"])

    return _create


def ai(ticket):
    return f"/api/v1/tickets/{ticket.id}/ai/"


# ------------------------------------------------------------------ triage
def test_new_ticket_is_triaged_into_pending_recommendations(new_ticket, setup, client_for):
    ticket = new_ticket()
    kinds = set(AIAnalysis.objects.filter(ticket=ticket, status="completed").values_list("kind", flat=True))
    assert kinds == {"classification", "priority", "routing"}
    assert all(a.is_mock and a.trigger == "ticket_created" for a in AIAnalysis.objects.filter(ticket=ticket))

    recs = {r.type: r for r in AIRecommendation.objects.filter(ticket=ticket)}
    assert recs["category"].value["category_id"] == str(setup["hvac"].id)
    assert recs["priority"].value == {"priority": "critical"}
    assert recs["assignee"].status == "pending"
    # Nothing was changed on the ticket: recommendations wait for a person by default.
    ticket.refresh_from_db()
    assert ticket.category_id is None and ticket.priority == "medium" and ticket.assigned_agent_id is None

    body = client_for(setup["ops"]).get(ai(ticket)).json()
    assert {a["kind"] for a in body["analyses"]} == kinds
    assert all(a["reasoning"].startswith("[mock]") or a["kind"] == "routing" for a in body["analyses"])


def test_ai_disabled_org_skips_triage(org, new_ticket):
    org.settings = {"ai_enabled": False}
    org.save()
    assert not AIAnalysis.objects.filter(ticket=new_ticket()).exists()


def test_manual_routing_policy_skips_routing(org, new_ticket):
    org.settings = {"routing_policy": "manual"}
    org.save()
    kinds = set(AIAnalysis.objects.filter(ticket=new_ticket()).values_list("kind", flat=True))
    assert kinds == {"classification", "priority"}


def test_auto_triage_applies_only_above_threshold_and_never_over_manual_priority(org, new_ticket, settings, setup):
    org.settings = {"ai_auto_triage": True}
    org.save()
    settings.AI_AUTO_APPLY_MIN_CONFIDENCE = 0.99  # mock confidence (<=0.75) is below it
    ticket = new_ticket()
    assert ticket.category_id is None

    settings.AI_AUTO_APPLY_MIN_CONFIDENCE = 0.5
    ticket = new_ticket()
    ticket.refresh_from_db()
    assert ticket.category_id == setup["hvac"].id
    assert ticket.priority == "critical" and ticket.priority_source == "ai"
    change = TicketHistory.objects.get(ticket=ticket, field="category")
    assert change.actor is None and change.actor_type == "ai"
    assert AIRecommendation.objects.get(ticket=ticket, type="category").status == "auto_applied"

    manual = new_ticket(priority="low")
    manual.refresh_from_db()
    assert manual.priority == "low" and manual.priority_source == "manual"
    assert AIRecommendation.objects.get(ticket=manual, type="priority").status == "pending"


def test_auto_routing_assigns_clear_winner(org, new_ticket, settings, setup, make_member):
    org.settings = {"routing_policy": "auto"}
    org.save()
    settings.AI_AUTO_APPLY_MIN_CONFIDENCE = 0.6
    busy = make_member(org, RoleCode.SUPPORT_AGENT)
    for n in range(4):  # give everyone but `agent` open work
        for m in (busy, setup["ops"]):
            Ticket.objects.create(
                organization=org,
                number=900 + n * 10 + (m == busy),
                title="x",
                description="y",
                customer=setup["customer"],
                assigned_agent=m.user,
                status="in_progress",
            )
    # `agent` is idle while the other two carry four open tickets each: a clear winner.
    ticket = new_ticket()
    ticket.refresh_from_db()
    routing = AIAnalysis.objects.get(ticket=ticket, kind="routing")
    assert float(routing.confidence) >= 0.6
    assert ticket.assigned_agent_id == setup["agent"].user_id
    assignment = TicketAssignment.objects.get(ticket=ticket, role="agent")
    assert assignment.source == "ai_auto" and assignment.assigned_by is None
    assert AIRecommendation.objects.get(ticket=ticket, type="assignee").status == "auto_applied"
    ranked = routing.output["agents"]
    assert ranked[0]["score"] >= ranked[-1]["score"]
    assert {"workload", "experience", "recency"} == set(ranked[0]["factors"])


def test_routing_works_when_explanations_fail(new_ticket, settings, monkeypatch):
    from apps.ai import client
    from apps.ai.providers.base import ProviderUnavailable

    class Down:
        name = "down"

        def complete_json(self, request, *, timeout):
            raise ProviderUnavailable("offline")

    settings.AI_MAX_RETRIES = 0
    monkeypatch.setattr(client, "get_provider", lambda: Down())
    ticket = new_ticket()
    assert AIAnalysis.objects.get(ticket=ticket, kind="classification").status == "failed"
    routing = AIAnalysis.objects.get(ticket=ticket, kind="routing")
    assert routing.status == "completed"  # deterministic ranking still delivered
    assert "Explanations unavailable" in routing.reasoning
    assert routing.output["agents"][0]["explanation"]


# --------------------------------------------------------------- decisions
def decide(client, rec, **body):
    return client.post(f"/api/v1/ai/recommendations/{rec.id}/decide/", body, format="json")


def test_accepting_category_applies_it_with_history(new_ticket, setup, client_for):
    ticket = new_ticket()
    rec = AIRecommendation.objects.get(ticket=ticket, type="category")
    r = decide(client_for(setup["ops"]), rec, decision="accept")
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    ticket.refresh_from_db()
    assert ticket.category_id == setup["hvac"].id
    change = TicketHistory.objects.get(ticket=ticket, field="category")
    assert change.actor == setup["ops"].user and change.actor_type == "user"
    assert decide(client_for(setup["ops"]), rec, decision="accept").status_code == 400  # already decided


def test_override_and_reject(new_ticket, setup, client_for):
    ticket = new_ticket()
    client = client_for(setup["ops"])
    prio = AIRecommendation.objects.get(ticket=ticket, type="priority")
    r = decide(client, prio, decision="override", value={"priority": "high"}, note="Not an outage")
    assert r.json()["status"] == "overridden" and r.json()["override_value"] == {"priority": "high"}
    ticket.refresh_from_db()
    assert ticket.priority == "high" and ticket.priority_source == "manual"
    assert (
        decide(client, AIRecommendation.objects.get(ticket=ticket, type="category"), decision="override").status_code
        == 400
    )  # value required
    rec = AIRecommendation.objects.get(ticket=ticket, type="assignee")
    assert decide(client, rec, decision="reject").json()["status"] == "rejected"


def test_accepting_assignee_records_ai_source(new_ticket, setup, client_for):
    ticket = new_ticket()
    rec = AIRecommendation.objects.get(ticket=ticket, type="assignee")
    decide(client_for(setup["ops"]), rec, decision="accept")
    assignment = TicketAssignment.objects.get(ticket=ticket, role="agent", unassigned_at__isnull=True)
    assert assignment.source == "ai_accepted" and str(assignment.assignee_id) == rec.value["user_id"]


def test_agents_can_use_ai_but_not_decide_and_customers_cannot_use_it(new_ticket, setup, client_for, org, make_member):
    ticket = new_ticket()
    agent = client_for(setup["agent"])
    assert agent.get(ai(ticket)).status_code == 200
    rec = AIRecommendation.objects.get(ticket=ticket, type="category")
    assert decide(agent, rec, decision="accept").status_code == 403  # support agents lack ai.override
    portal = make_member(org, RoleCode.CUSTOMER)
    CustomerContact.objects.create(customer=setup["customer"], user=portal.user, name="IT")
    assert client_for(portal).get(ai(ticket)).status_code == 403


def run_and_poll(client, captured, url, body):
    """POST returns 202 with pending analyses; the work runs after commit (Celery). Then poll each one."""
    with captured(execute=True):
        r = client.post(url, body, format="json")
    assert r.status_code == 202
    started = r.json() if isinstance(r.json(), list) else [r.json()]
    assert all(a["status"] == "pending" for a in started)
    return [client.get(f"/api/v1/ai/analyses/{a['id']}/").json() for a in started]


def test_on_demand_summary_and_response_suggestion(new_ticket, setup, client_for, django_capture_on_commit_callbacks):
    ticket = new_ticket()
    client = client_for(setup["ops"])
    client.post(
        f"/api/v1/tickets/{ticket.id}/comments/", {"body": "VIP customer", "visibility": "internal"}, format="json"
    )
    done = run_and_poll(
        client, django_capture_on_commit_callbacks, ai(ticket), {"kinds": ["summary", "response_suggestion"]}
    )
    by_kind = {a["kind"]: a for a in done}
    assert by_kind["summary"]["status"] == "completed" and by_kind["summary"]["output"]["summary"]
    draft = by_kind["response_suggestion"]["output"]["draft"]
    assert "VIP customer" not in draft  # internal notes never reach customer-facing drafts


def test_identical_request_reuses_recent_result(new_ticket, setup, client_for, django_capture_on_commit_callbacks):
    ticket = new_ticket()
    client = client_for(setup["ops"])
    run_and_poll(client, django_capture_on_commit_callbacks, ai(ticket), {"kinds": ["summary"]})
    second = run_and_poll(client, django_capture_on_commit_callbacks, ai(ticket), {"kinds": ["summary"]})[0]
    assert second["status"] == "completed" and second["latency_ms"] == 0


def test_ai_data_is_isolated_between_orgs(new_ticket, setup, client_for, other_org, make_member):
    ticket = new_ticket()
    outsider = client_for(make_member(other_org, RoleCode.ORG_ADMIN))
    analysis = AIAnalysis.objects.filter(ticket=ticket).first()
    assert outsider.get(ai(ticket)).status_code == 404
    assert outsider.get(f"/api/v1/ai/analyses/{analysis.id}/").status_code == 404
    assert outsider.get("/api/v1/ai/recommendations/").json()["count"] == 0
    rec = AIRecommendation.objects.filter(ticket=ticket).first()
    assert decide(outsider, rec, decision="accept").status_code == 404


# ---------------------------------------------------------------- knowledge
def close_with_resolution(client, ticket, captured):
    with captured(execute=True):
        client.post(
            f"/api/v1/tickets/{ticket.id}/transition/",
            {"status": "resolved", "resolution_notes": "Cleaned the condenser coils; cooling restored."},
            format="json",
        )
        client.post(f"/api/v1/tickets/{ticket.id}/transition/", {"status": "closed"}, format="json")


def test_closed_ticket_becomes_draft_article_that_needs_review(
    new_ticket, setup, client_for, django_capture_on_commit_callbacks
):
    ticket = new_ticket()
    ops, agent = client_for(setup["ops"]), client_for(setup["agent"])
    close_with_resolution(ops, ticket, django_capture_on_commit_callbacks)
    article = KnowledgeArticle.objects.get(source_ticket=ticket)
    assert article.status == "draft" and article.source == "ai_extracted"
    assert "Cleaned the condenser coils" in article.body

    assert agent.get("/api/v1/knowledge/articles/").json()["count"] == 0  # drafts hidden from readers
    assert agent.post(f"/api/v1/knowledge/articles/{article.id}/publish/").status_code == 403
    r = ops.post(f"/api/v1/knowledge/articles/{article.id}/publish/")
    assert r.status_code == 200 and r.json()["status"] == "published" and r.json()["reviewed_by"]
    assert agent.get("/api/v1/knowledge/articles/").json()["count"] == 1
    assert ops.post(f"/api/v1/knowledge/articles/{article.id}/submit/").status_code == 400  # invalid move


def test_assistant_answers_from_published_sources_only(setup, client_for, org, django_capture_on_commit_callbacks):
    KnowledgeArticle.objects.create(
        organization=org, title="Clearing printer jams", body="Open tray B. Remove paper.", status="published"
    )
    KnowledgeArticle.objects.create(
        organization=org, title="Secret draft about printer jams", body="draft", status="draft"
    )
    client = client_for(setup["agent"])
    answer = run_and_poll(
        client, django_capture_on_commit_callbacks, "/api/v1/ai/assistant/", {"question": "How do I fix a printer jam?"}
    )[0]
    out = answer["output"]
    titles = [s["title"] for s in out["sources"]]
    assert titles == ["Clearing printer jams"]
    assert all(i.startswith(("article:", "ticket:")) for i in out["source_ids"])
    assert len(client.get("/api/v1/ai/assistant/").json()) == 1


def test_insights_generated_from_aggregates(setup, client_for, org, django_capture_on_commit_callbacks):
    for n in range(4):
        Ticket.objects.create(
            organization=org,
            number=n + 1,
            title="AC",
            description="d",
            customer=setup["customer"],
            category=setup["hvac"],
        )
    client = client_for(setup["ops"])
    run_and_poll(client, django_capture_on_commit_callbacks, "/api/v1/ai/insights/generate/", {"days": 30})
    insights = client.get("/api/v1/ai/insights/").json()["results"]
    assert any(i["type"] == "recurring_issue" and "HVAC" in i["title"] for i in insights)
    dismissed = client.post(f"/api/v1/ai/insights/{insights[0]['id']}/dismiss/").json()
    assert dismissed["is_dismissed"] is True
    assert client_for(setup["agent"]).get("/api/v1/ai/insights/").status_code == 403  # needs analytics.view
    assert AIInsight.objects.filter(organization=org).count() >= 1


def test_ai_status_never_exposes_the_key(client_for, setup, settings):
    settings.AI_API_KEY = "sk-ant-should-never-leak"
    response = client_for(setup["ops"]).get("/api/v1/ai/status/")
    assert "sk-ant" not in response.content.decode()
    assert response.json()["mock_mode"] is True and response.json()["provider"] == "mock"


def test_routing_prefers_front_line_roles_over_admins(new_ticket, setup, admin):
    ticket = new_ticket()  # `admin` (org admin) has no open tickets but should not be the default target
    names = [c["name"] for c in AIAnalysis.objects.get(ticket=ticket, kind="routing").output["agents"]]
    assert admin.user.full_name not in names
    assert setup["agent"].user.full_name in names
