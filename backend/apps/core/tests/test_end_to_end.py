"""
The whole service journey through the public API, as the real roles, with events live:

customer raises a request in the portal → SLA clock starts → AI triage (mock) runs →
ops assigns an agent (who is notified) → agent replies (first response met) → a work
order is dispatched to a technician (notified) → technician travels, works, uploads a
photo and completes → agent resolves → customer confirms and rates → analytics,
SLA report and outbound webhook all reflect it.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.customers.models import Customer
from apps.field_service.models import Technician
from apps.integrations import net
from apps.notifications.models import Notification
from apps.organizations.catalog import RoleCode
from apps.sla.models import SLAInstance, SLAPolicy

pytestmark = pytest.mark.django_db
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def receiver(monkeypatch):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    real = net.resolve_public
    monkeypatch.setattr(net, "resolve_public", lambda h, p: "127.0.0.1" if h == "erp.example.com" else real(h, p))
    yield f"http://erp.example.com:{server.server_address[1]}/hooks", received
    server.shutdown()


def test_customer_to_resolution_journey(org, make_member, client_for, receiver, django_capture_on_commit_callbacks):
    run = django_capture_on_commit_callbacks
    SLAPolicy.objects.filter(organization=org).update(business_hours=None)  # 24/7 keeps expectations simple
    bank = Customer.objects.create(organization=org, name="Himalayan Bank", tier="enterprise")
    admin = make_member(org, RoleCode.ORG_ADMIN, email="admin@e2e.test")
    ops = make_member(org, RoleCode.OPS_MANAGER, email="ops@e2e.test")
    agent = make_member(org, RoleCode.SUPPORT_AGENT, email="ana@e2e.test")
    tech_m = make_member(org, RoleCode.FIELD_TECHNICIAN, email="tariq@e2e.test")
    cust = make_member(org, RoleCode.CUSTOMER, email="sita@bank.test")
    bank.contacts.create(name="Sita", email="sita@bank.test", user=cust.user)
    as_admin, as_ops, as_agent, as_tech, as_customer = (client_for(m) for m in (admin, ops, agent, tech_m, cust))

    # An outbound webhook subscribed to the journey's key events.
    hook_url, received = receiver
    integration = as_admin.post(
        "/api/v1/integrations/", {"kind": "webhook", "provider": "generic", "name": "ERP"}, format="json"
    ).json()
    as_admin.post(
        f"/api/v1/integrations/{integration['id']}/endpoints/",
        {"url": hook_url, "events": ["ticket.created", "work_order.status_changed", "ticket.status_changed"]},
        format="json",
    )

    # 1. The customer raises a request in the portal.
    with run(execute=True):
        r = as_customer.post(
            "/api/v1/portal/tickets/",
            {"title": "ATM 4 keeps cards", "description": "Swallowed three cards today."},
            format="json",
        )
    assert r.status_code == 201, r.json()
    ticket_id = r.json()["id"]
    assert r.json()["status_label"] == "Received"
    sla = SLAInstance.objects.get(ticket_id=ticket_id)
    assert sla.response_status == "on_track"
    ai = as_ops.get(f"/api/v1/tickets/{ticket_id}/ai/").json()
    assert "analyses" in ai, ai
    assert {a["kind"] for a in ai["analyses"]} >= {"classification", "priority"}  # triage ran (mock provider)

    # 2. Ops assigns an agent, who is notified.
    with run(execute=True):
        assert (
            as_ops.post(
                f"/api/v1/tickets/{ticket_id}/assign/", {"agent": str(agent.user.id)}, format="json"
            ).status_code
            == 200
        )
    assert Notification.objects.filter(recipient=agent.user, type="ticket_assigned").exists()

    # 3. The agent replies publicly: first response met.
    with run(execute=True):
        as_agent.post(
            f"/api/v1/tickets/{ticket_id}/comments/",
            {"body": "A technician is on the way.", "visibility": "public"},
            format="json",
        )
    sla.refresh_from_db()
    assert sla.response_status == "met"

    # 4. Ops dispatches a work order to the technician, who is notified.
    technician = Technician.objects.get(user=tech_m.user)
    with run(execute=True):
        wo = as_ops.post(
            "/api/v1/work-orders/", {"ticket": ticket_id, "technician": str(technician.id)}, format="json"
        ).json()
    assert Notification.objects.filter(recipient=tech_m.user, type="work_order_assigned").exists()

    # 5. The technician works the job and completes it with evidence.
    with run(execute=True):
        for step in ("accepted", "en_route", "on_site", "in_progress"):
            assert (
                as_tech.post(f"/api/v1/work-orders/{wo['id']}/advance/", {"status": step}, format="json").status_code
                == 200
            )
        as_tech.post(
            f"/api/v1/work-orders/{wo['id']}/evidence/",
            {"file": SimpleUploadedFile("after.png", PNG), "kind": "after_photo"},
            format="multipart",
        )
        done = as_tech.post(
            f"/api/v1/work-orders/{wo['id']}/advance/",
            {"status": "completed", "completion_summary": "Replaced the card reader."},
            format="json",
        )
    assert done.status_code == 200 and done.json()["status"] == "completed"

    # 6. The agent resolves; the customer confirms and rates in the portal.
    with run(execute=True):
        as_agent.post(
            f"/api/v1/tickets/{ticket_id}/transition/",
            {"status": "resolved", "resolution_notes": "Card reader replaced on site."},
            format="json",
        )
        detail = as_customer.get(f"/api/v1/portal/tickets/{ticket_id}/").json()
        assert detail["actions"]["confirm"] and detail["status_label"] == "Resolved"
        assert as_customer.post(f"/api/v1/portal/tickets/{ticket_id}/confirm/").json()["status"] == "closed"
    assert (
        as_customer.post(
            "/api/v1/portal/feedback/", {"ticket": ticket_id, "rating": 5, "comment": "Fast!"}, format="json"
        ).status_code
        == 201
    )

    # 7. Everything downstream reflects it.
    sla.refresh_from_db()
    assert sla.resolution_status == "met"
    report = as_ops.get("/api/v1/sla/report/").json()
    assert report["resolution_compliance"] == 1.0
    sat = as_ops.get("/api/v1/analytics/reports/customer_satisfaction/").json()["rows"]
    assert sat == [{"customer": "Himalayan Bank", "responses": 1, "avg_rating": 5.0, "satisfied": 1.0, "unhappy": 0}]
    types = [e["type"] for e in received]
    assert types[0] == "ticket.created" and "work_order.status_changed" in types and "ticket.status_changed" in types
    assert all("Swallowed" not in json.dumps(e) for e in received)  # descriptions aren't broadcast
    with mock.patch.object(net, "request", side_effect=AssertionError("no egress expected")):
        assert as_customer.get("/api/v1/portal/tickets/").json()["results"][0]["feedback"]["rating"] == 5
