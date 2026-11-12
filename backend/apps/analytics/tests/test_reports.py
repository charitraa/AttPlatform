import csv
import io
from datetime import UTC, datetime, timedelta

import pytest

from apps.audit.models import AuditLog
from apps.customers.models import Customer
from apps.organizations.catalog import RoleCode
from apps.portal.models import CustomerFeedback
from apps.tickets.models import Ticket

pytestmark = pytest.mark.django_db


@pytest.fixture
def data(org, make_member):
    org.timezone = "Asia/Kathmandu"
    org.save()
    ops = make_member(org, RoleCode.OPS_MANAGER, email="ops@acme.test")
    agent = make_member(org, RoleCode.SUPPORT_AGENT, email="ana@acme.test")
    agent.user.first_name, agent.user.last_name = "Ana", "Agent"
    agent.user.save()
    customer = Customer.objects.create(organization=org, name="=cmd|' /C calc'!A0")  # CSV-injection probe
    base = datetime(2026, 11, 10, 4, 0, tzinfo=UTC)  # 09:45 in Kathmandu on 10 Nov
    tickets = []
    for i, (hours, resolved) in enumerate([(2, True), (6, True), (0, False)]):
        t = Ticket.objects.create(
            organization=org, number=i + 1, title=f"T{i}", description="d", customer=customer, assigned_agent=agent.user
        )
        Ticket.objects.filter(pk=t.pk).update(
            created_at=base,
            first_response_at=base + timedelta(hours=1),
            resolved_at=base + timedelta(hours=hours) if resolved else None,
            status="resolved" if resolved else "open",
        )
        tickets.append(t)
    CustomerFeedback.objects.create(organization=org, customer=customer, ticket=tickets[0], rating=5)
    CustomerFeedback.objects.create(organization=org, customer=customer, ticket=tickets[1], rating=2)
    CustomerFeedback.objects.update(created_at=base + timedelta(hours=8))  # inside the report window
    return {"ops": ops, "agent": agent}


Q = "?start=2026-11-09&end=2026-11-11"


def test_ticket_volume_uses_the_organization_day(client_for, data):
    r = client_for(data["ops"]).get(f"/api/v1/analytics/reports/ticket_volume/{Q}").json()
    assert [row["date"] for row in r["rows"]] == ["2026-11-09", "2026-11-10", "2026-11-11"]
    day = r["rows"][1]
    assert (day["created"], day["resolved"], day["avg_first_response_h"], day["avg_resolution_h"]) == (3, 2, 1.0, 4.0)


def test_agent_performance_and_satisfaction(client_for, data):
    client = client_for(data["ops"])
    agents = client.get(f"/api/v1/analytics/reports/agent_performance/{Q}").json()["rows"]
    assert agents == [
        {
            "agent": "Ana Agent",
            "assigned": 3,
            "resolved": 2,
            "avg_first_response_h": 1.0,
            "avg_resolution_h": 4.0,
            "sla_breaches": 0,
            "reopened": 0,
        }
    ]
    sat = client.get(f"/api/v1/analytics/reports/customer_satisfaction/{Q}").json()["rows"]
    assert sat[0]["responses"] == 2 and sat[0]["avg_rating"] == 3.5 and sat[0]["unhappy"] == 1


def test_every_report_renders(client_for, data):
    client = client_for(data["ops"])
    names = [r["name"] for r in client.get("/api/v1/analytics/reports/").json()]
    assert len(names) == 7
    for name in names:
        body = client.get(f"/api/v1/analytics/reports/{name}/{Q}").json()
        assert body["columns"] and isinstance(body["rows"], list), name


def test_csv_export_is_safe_and_audited(client_for, data):
    r = client_for(data["ops"]).get(f"/api/v1/analytics/reports/customer_satisfaction/{Q}&export=csv")
    assert r.status_code == 200 and r["Content-Type"].startswith("text/csv")
    assert 'filename="customer_satisfaction_2026-11-09_2026-11-11.csv"' in r["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0][0] == "Customer" and rows[1][0] == "'=cmd|' /C calc'!A0"  # neutralised formula
    entry = AuditLog.objects.get(action="analytics.exported")
    assert entry.target_id == "customer_satisfaction" and entry.changes["rows"] == 1


def test_validation_and_permissions(client_for, data):
    ops = client_for(data["ops"])
    assert ops.get("/api/v1/analytics/reports/nope/").status_code == 404
    assert ops.get("/api/v1/analytics/reports/ticket_volume/?start=2026-11-10&end=2026-11-01").status_code == 400
    assert ops.get("/api/v1/analytics/reports/ticket_volume/?start=2025-01-01&end=2026-11-01").status_code == 400
    assert ops.get("/api/v1/analytics/reports/ticket_volume/?start=yesterday").status_code == 400
    assert client_for(data["agent"]).get("/api/v1/analytics/reports/").status_code == 403
