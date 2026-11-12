from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.customers.models import Customer
from apps.field_service.models import (
    Appointment,
    Skill,
    Technician,
    TechnicianAvailability,
    TechnicianLocation,
    TechnicianSkill,
    WorkOrder,
)
from apps.field_service.selectors import rank_technicians
from apps.organizations.catalog import RoleCode
from apps.tickets.models import Ticket, TicketCategory, TicketComment

pytestmark = pytest.mark.django_db
URL = "/api/v1/work-orders/"
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82"
)
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@pytest.fixture
def fs(org, make_member):
    customer = Customer.objects.create(
        organization=org, name="Annapurna Cold Storage", address_line1="Ring Rd", city="Chitwan"
    )
    category = TicketCategory.objects.create(organization=org, name="Refrigeration")
    ticket = Ticket.objects.create(
        organization=org,
        number=1,
        title="Compressor failure",
        description="Cold room warm",
        customer=customer,
        category=category,
        priority="high",
    )
    ops = make_member(org, RoleCode.OPS_MANAGER, email="ops@acme.test")
    agent = make_member(org, RoleCode.SUPPORT_AGENT, email="agent@acme.test")
    t1 = make_member(org, RoleCode.FIELD_TECHNICIAN, email="tariq@acme.test")
    t2 = make_member(org, RoleCode.FIELD_TECHNICIAN, email="tina@acme.test")
    tech1 = Technician.objects.get(user=t1.user)
    tech2 = Technician.objects.get(user=t2.user)
    tech1.hourly_cost, tech1.currency = Decimal("1200.00"), "NPR"
    tech1.save()
    return {
        "customer": customer,
        "category": category,
        "ticket": ticket,
        "ops": ops,
        "agent": agent,
        "t1": t1,
        "t2": t2,
        "tech1": tech1,
        "tech2": tech2,
    }


def make_wo(client_for, fs, **extra):
    r = client_for(fs["ops"]).post(URL, {"ticket": str(fs["ticket"].id), **extra}, format="json")
    assert r.status_code == 201, r.json()
    return r.json()


def url(wo, suffix=""):
    return f"{URL}{wo['id']}/{suffix}"


def upload(client, wo, kind="after_photo", name="after.png", content=PNG):
    return client.post(
        url(wo, "evidence/"), {"file": SimpleUploadedFile(name, content), "kind": kind}, format="multipart"
    )


# --------------------------------------------------------------- technicians
def test_profiles_created_automatically_and_listed(client_for, fs):
    body = client_for(fs["agent"]).get("/api/v1/technicians/").json()
    assert {t["user"]["email"] for t in body["results"]} == {"tariq@acme.test", "tina@acme.test"}


def test_customers_cannot_see_technicians(client_for, fs, org, make_member):
    assert client_for(make_member(org, RoleCode.CUSTOMER)).get("/api/v1/technicians/").status_code == 403


def test_technician_updates_own_profile_but_not_to_on_leave(client_for, fs):
    client = client_for(fs["t1"])
    r = client.patch("/api/v1/technicians/me/", {"location_sharing_enabled": True, "status": "off_duty"}, format="json")
    assert r.status_code == 200 and r.json()["location_sharing_enabled"] is True and r.json()["status"] == "off_duty"
    assert client.patch("/api/v1/technicians/me/", {"status": "on_leave"}, format="json").status_code == 400


def test_availability_self_service_and_limits(client_for, fs):
    start = timezone.now() + timedelta(days=1)
    body = {"type": "time_off", "starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=8)).isoformat()}
    own = client_for(fs["t1"]).post(f"/api/v1/technicians/{fs['tech1'].id}/availability/", body, format="json")
    assert own.status_code == 201
    other = client_for(fs["t1"]).post(f"/api/v1/technicians/{fs['tech2'].id}/availability/", body, format="json")
    assert other.status_code == 403
    bad = {**body, "ends_at": start.isoformat()}
    assert (
        client_for(fs["ops"])
        .post(f"/api/v1/technicians/{fs['tech2'].id}/availability/", bad, format="json")
        .status_code
        == 400
    )


def test_skills_replace_and_validation(client_for, fs, org):
    skill = Skill.objects.create(organization=org, name="Refrigeration")
    r = client_for(fs["ops"]).put(
        f"/api/v1/technicians/{fs['tech1'].id}/skills/", [{"skill": str(skill.id), "level": 4}], format="json"
    )
    assert r.status_code == 200 and r.json() == [{"skill": str(skill.id), "name": "Refrigeration", "level": 4}]
    bad = client_for(fs["ops"]).put(
        f"/api/v1/technicians/{fs['tech1'].id}/skills/", [{"skill": str(skill.id), "level": 9}], format="json"
    )
    assert bad.status_code == 400


# --------------------------------------------------------------- work orders
def test_create_from_ticket_copies_context_and_notes_ticket(client_for, fs):
    wo = make_wo(client_for, fs)
    assert wo["reference"] == "WO-000001" and wo["status"] == "created"
    assert wo["customer"]["name"] == "Annapurna Cold Storage" and wo["priority"] == "high"
    assert wo["title"] == "Compressor failure" and wo["service_address"] == "Ring Rd, Chitwan"
    note = TicketComment.objects.get(ticket=fs["ticket"])
    assert note.visibility == "internal" and "WO-000001" in note.body


def test_create_validation_and_permissions(client_for, fs, other_org):
    client = client_for(fs["ops"])
    assert client.post(URL, {"title": "x"}, format="json").status_code == 400  # no customer or ticket
    foreign = Customer.objects.create(organization=other_org, name="Foreign")
    assert client.post(URL, {"customer": str(foreign.id), "title": "x"}, format="json").status_code == 400
    assert client_for(fs["agent"]).post(URL, {"ticket": str(fs["ticket"].id)}, format="json").status_code == 403


def test_assign_syncs_ticket_technician_and_validates(client_for, fs, other_org, make_member):
    wo = make_wo(client_for, fs)
    client = client_for(fs["ops"])
    r = client.post(url(wo, "assign/"), {"technician": str(fs["tech1"].id)}, format="json")
    assert r.json()["status"] == "assigned" and r.json()["technician"]["name"] == fs["tech1"].user.full_name
    fs["ticket"].refresh_from_db()
    assert fs["ticket"].assigned_technician_id == fs["t1"].user_id

    outsider = Technician.objects.get(user=make_member(other_org, RoleCode.FIELD_TECHNICIAN).user)
    assert client.post(url(wo, "assign/"), {"technician": str(outsider.id)}, format="json").status_code == 400


def test_full_technician_workflow_with_costs(client_for, fs):
    wo = make_wo(client_for, fs, technician=str(fs["tech1"].id))
    tech = client_for(fs["t1"])

    def step(status, **extra):
        return tech.post(url(wo, "advance/"), {"status": status, **extra}, format="json")

    assert step("on_site").status_code == 400  # must accept first
    assert step("accepted").json()["next_steps"] == ["en_route", "on_site"]
    assert step("en_route").status_code == 200
    fs["tech1"].refresh_from_db()
    assert fs["tech1"].status == "busy"
    step("on_site", lat="27.70", lng="85.32")
    step("in_progress")
    WorkOrder.objects.filter(pk=wo["id"]).update(actual_start=timezone.now() - timedelta(minutes=90))

    r = step("completed")
    assert r.status_code == 400 and "completion_summary" in r.json()["error"]["details"]
    r = step("completed", completion_summary="Replaced start capacitor.")
    assert r.status_code == 400 and "evidence" in r.json()["error"]["details"]

    assert upload(tech, wo, "before_photo", "before.png").status_code == 201
    assert upload(tech, wo, "after_photo").status_code == 201
    r = step(
        "completed",
        completion_summary="Replaced start capacitor.",
        parts_used=[{"name": "Capacitor 45uF", "quantity": 2, "unit_cost": "750.00"}],
    )
    body = r.json()
    assert r.status_code == 200 and body["status"] == "completed"
    assert body["parts_cost"] == "1500.00" and body["labor_minutes"] in (90, 91)
    assert Decimal(body["labor_cost"]) == (Decimal("1200") * body["labor_minutes"] / 60).quantize(Decimal("0.01"))
    fs["tech1"].refresh_from_db()
    assert fs["tech1"].status == "available"
    assert TicketComment.objects.filter(ticket=fs["ticket"], body__contains="completed by").exists()
    log = [e["to_status"] for e in tech.get(url(wo, "status-log/")).json()]
    assert log == ["created", "assigned", "accepted", "en_route", "on_site", "in_progress", "completed"]


def test_only_assigned_technician_advances(client_for, fs):
    wo = make_wo(client_for, fs, technician=str(fs["tech1"].id))
    r = client_for(fs["t2"]).post(url(wo, "advance/"), {"status": "accepted"}, format="json")
    assert r.status_code == 404  # not even visible to another technician
    assert client_for(fs["ops"]).post(url(wo, "advance/"), {"status": "accepted"}, format="json").status_code == 403


def test_decline_and_cancel(client_for, fs):
    wo = make_wo(client_for, fs, technician=str(fs["tech1"].id))
    tech = client_for(fs["t1"])
    assert tech.post(url(wo, "decline/"), {"reason": ""}, format="json").status_code == 400
    r = tech.post(url(wo, "decline/"), {"reason": "Not certified for ammonia systems"}, format="json")
    assert r.status_code == 200
    detail = client_for(fs["ops"]).get(url(wo)).json()
    assert detail["status"] == "created" and detail["technician"] is None
    assert tech.post(url(wo, "cancel/"), {"reason": "x"}, format="json").status_code == 403
    r = client_for(fs["ops"]).post(url(wo, "cancel/"), {"reason": "Customer fixed it"}, format="json")
    assert r.json()["status"] == "cancelled" and r.json()["cancelled_reason"] == "Customer fixed it"
    assert client_for(fs["ops"]).post(url(wo, "cancel/"), {"reason": "again"}, format="json").status_code == 400


def complete(client_for, fs, wo):
    tech = client_for(fs["t1"])
    for s in ("accepted", "en_route", "on_site", "in_progress"):
        tech.post(url(wo, "advance/"), {"status": s}, format="json")
    upload(tech, wo)
    tech.post(url(wo, "advance/"), {"status": "completed", "completion_summary": "Done"}, format="json")
    return tech


def test_customer_confirmation(client_for, fs):
    wo = make_wo(client_for, fs, technician=str(fs["tech1"].id))
    tech = client_for(fs["t1"])
    assert tech.post(url(wo, "confirm/"), {"signed_by": "Ram"}, format="json").status_code == 400  # not completed
    complete(client_for, fs, wo)
    assert tech.post(url(wo, "confirm/"), {"signed_by": "Ram", "rating": 6}, format="json").status_code == 400
    r = tech.post(url(wo, "confirm/"), {"signed_by": "Ram Thapa", "rating": 5, "comment": "Fast"}, format="json")
    assert r.status_code == 200 and r.json()["customer_signed_by"] == "Ram Thapa" and r.json()["customer_rating"] == 5
    assert r.json()["capabilities"]["confirm"] is False
    assert tech.post(url(wo, "confirm/"), {"signed_by": "Ram"}, format="json").status_code == 409


# ---------------------------------------------------------------- evidence
def test_evidence_rules_and_isolation(client_for, fs, other_org, make_member):
    wo = make_wo(client_for, fs, technician=str(fs["tech1"].id))
    tech = client_for(fs["t1"])
    r = upload(tech, wo, "after_photo", "report.pdf", PDF)  # photos must be images
    assert r.status_code == 400
    assert upload(tech, wo, "document", "report.pdf", PDF).status_code == 201
    ev = upload(tech, wo).json()
    download = tech.get(ev["download_url"])
    assert download.status_code == 200 and b"".join(download.streaming_content) == PNG
    assert client_for(fs["t2"]).get(ev["download_url"]).status_code == 404
    assert client_for(make_member(other_org, RoleCode.ORG_ADMIN)).get(ev["download_url"]).status_code == 404


# ---------------------------------------------------------------- scheduling
def slot(hours_from_now, length=2):
    start = (timezone.now() + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        hours=hours_from_now
    )
    return {"starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=length)).isoformat()}


def test_schedule_requires_technician_and_prevents_double_booking(client_for, fs):
    client = client_for(fs["ops"])
    wo1 = make_wo(client_for, fs)
    assert client.post(url(wo1, "schedule/"), slot(9), format="json").status_code == 400  # no technician
    client.post(url(wo1, "assign/"), {"technician": str(fs["tech1"].id)}, format="json")
    r = client.post(url(wo1, "schedule/"), slot(9), format="json")
    assert r.status_code == 200 and r.json()["appointment"] and r.json()["warnings"] == []

    wo2 = make_wo(client_for, fs, technician=str(fs["tech1"].id))
    clash = client.post(url(wo2, "schedule/"), slot(10), format="json")
    assert clash.status_code == 409 and "WO-000001" in clash.json()["error"]["message"]
    assert client.post(url(wo2, "schedule/"), slot(11), format="json").status_code == 200  # back-to-back is fine

    # Rescheduling wo1 replaces its appointment instead of conflicting with itself.
    assert client.post(url(wo1, "schedule/"), slot(8, 3), format="json").status_code == 200
    assert Appointment.objects.filter(work_order_id=wo1["id"], status="confirmed").count() == 1


def test_database_refuses_overlapping_confirmed_appointments(fs, org):
    wo = WorkOrder.objects.create(organization=org, number=99, customer=fs["customer"], title="x")
    start = timezone.now() + timedelta(days=3)
    Appointment.objects.create(
        organization=org, work_order=wo, technician=fs["tech1"], starts_at=start, ends_at=start + timedelta(hours=2)
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Appointment.objects.create(
            organization=org,
            work_order=wo,
            technician=fs["tech1"],
            starts_at=start + timedelta(hours=1),
            ends_at=start + timedelta(hours=3),
        )
    # Cancelled appointments don't block the slot.
    Appointment.objects.create(
        organization=org,
        work_order=wo,
        technician=fs["tech1"],
        status="cancelled",
        starts_at=start + timedelta(hours=1),
        ends_at=start + timedelta(hours=3),
    )


def test_time_off_blocks_and_shift_warns(client_for, fs):
    client = client_for(fs["ops"])
    wo = make_wo(client_for, fs, technician=str(fs["tech1"].id))
    s = slot(14)
    start = timezone.datetime.fromisoformat(s["starts_at"])
    TechnicianAvailability.objects.create(
        technician=fs["tech1"], type="time_off", starts_at=start, ends_at=start + timedelta(hours=4)
    )
    assert client.post(url(wo, "schedule/"), s, format="json").status_code == 400
    day = start.replace(hour=0)
    TechnicianAvailability.objects.create(
        technician=fs["tech1"], type="shift", starts_at=day + timedelta(hours=9), ends_at=day + timedelta(hours=13)
    )
    r = client.post(url(wo, "schedule/"), slot(20), format="json")
    assert r.status_code == 200 and "outside the technician's shift" in r.json()["warnings"][0]


def test_schedule_view_scopes_technicians_to_their_own_calendar(client_for, fs):
    client = client_for(fs["ops"])
    wo = make_wo(client_for, fs, technician=str(fs["tech1"].id))
    client.post(url(wo, "schedule/"), slot(9), format="json")
    start = timezone.now().isoformat()
    end = (timezone.now() + timedelta(days=7)).isoformat()
    params = {"start": start, "end": end}
    staff = client.get("/api/v1/schedule/", params).json()
    assert len(staff["technicians"]) == 2 and len(staff["appointments"]) == 1
    mine = client_for(fs["t2"]).get("/api/v1/schedule/", params).json()
    assert [t["id"] for t in mine["technicians"]] == [str(fs["tech2"].id)] and mine["appointments"] == []
    too_long = {"start": start, "end": (timezone.now() + timedelta(days=40)).isoformat()}
    assert client.get("/api/v1/schedule/", too_long).status_code == 400


# ---------------------------------------------------------------- visibility
def test_technicians_see_only_their_work_orders(client_for, fs, other_org, make_member):
    mine = make_wo(client_for, fs, technician=str(fs["tech1"].id))
    other = make_wo(client_for, fs, technician=str(fs["tech2"].id))
    ids = {w["id"] for w in client_for(fs["t1"]).get(URL).json()["results"]}
    assert ids == {mine["id"]}
    assert client_for(fs["t1"]).get(url(other)).status_code == 404
    outsider = client_for(make_member(other_org, RoleCode.ORG_ADMIN))
    assert outsider.get(URL).json()["count"] == 0 and outsider.get(url(mine)).status_code == 404


# ------------------------------------------------------------------ location
def test_location_is_opt_in_and_only_during_active_jobs(client_for, fs):
    tech = client_for(fs["t1"])
    ping = {"lat": "27.700000", "lng": "85.320000", "accuracy_m": 12}
    assert tech.post("/api/v1/technicians/me/location/", ping, format="json").status_code == 409  # sharing off
    tech.patch("/api/v1/technicians/me/", {"location_sharing_enabled": True}, format="json")
    assert tech.post("/api/v1/technicians/me/location/", ping, format="json").status_code == 409  # no active job
    wo = make_wo(client_for, fs, technician=str(fs["tech1"].id))
    tech.post(url(wo, "advance/"), {"status": "accepted"}, format="json")
    tech.post(url(wo, "advance/"), {"status": "en_route"}, format="json")
    assert tech.post("/api/v1/technicians/me/location/", ping, format="json").status_code == 201
    loc = TechnicianLocation.objects.get()
    assert str(loc.work_order_id) == wo["id"]

    assert client_for(fs["agent"]).get(f"/api/v1/technicians/{fs['tech1'].id}/location/").status_code == 403
    r = client_for(fs["ops"]).get(f"/api/v1/technicians/{fs['tech1'].id}/location/")
    assert r.json()["location"]["lat"] == "27.700000"


def test_old_locations_are_purged(fs):
    from apps.field_service.services import purge_old_locations

    loc = TechnicianLocation.objects.create(technician=fs["tech1"], lat=1, lng=1)
    TechnicianLocation.objects.filter(pk=loc.pk).update(recorded_at=timezone.now() - timedelta(days=31))
    TechnicianLocation.objects.create(technician=fs["tech1"], lat=2, lng=2)
    assert purge_old_locations() == 1 and TechnicianLocation.objects.count() == 1


# ------------------------------------------------------------------- scoring
def test_ranking_prefers_skills_and_proximity_and_explains_blocks(fs, org):
    skill = Skill.objects.create(organization=org, name="Refrigeration")
    skill.ticket_categories.add(fs["category"])
    TechnicianSkill.objects.create(technician=fs["tech2"], skill=skill, level=5)
    fs["tech1"].home_lat, fs["tech1"].home_lng = Decimal("27.68"), Decimal("84.43")  # in Chitwan
    fs["tech1"].save()
    fs["tech2"].home_lat, fs["tech2"].home_lng = Decimal("27.70"), Decimal("85.32")  # Kathmandu, ~90 km away
    fs["tech2"].save()

    ranked = rank_technicians(org, category_id=fs["category"].id, lat=Decimal("27.68"), lng=Decimal("84.43"))
    tech1_id, tech2_id = str(fs["tech1"].id), str(fs["tech2"].id)
    assert ranked[0].technician_id == tech2_id  # required skill outweighs distance
    assert ranked[0].matched_skills == ["Refrigeration"] and ranked[1].missing_skills == ["Refrigeration"]
    assert ranked[1].distance_km == 0.0 and ranked[0].distance_km > 80

    fs["tech2"].status = "on_leave"
    fs["tech2"].save()
    ranked = rank_technicians(org, category_id=fs["category"].id, include_blocked=True)
    assert ranked[-1].technician_id == tech2_id and ranked[-1].blocked_reason == "On leave"
    assert [r.technician_id for r in rank_technicians(org, category_id=fs["category"].id)] == [tech1_id]


def test_suggest_technicians_endpoint(client_for, fs):
    wo = make_wo(client_for, fs)
    body = client_for(fs["ops"]).get(url(wo, "suggest-technicians/")).json()
    assert set(body["weights"]) == {"skills", "availability", "workload", "distance"}
    assert len(body["candidates"]) == 2


def test_dashboard_reports_field_service_figures(client_for, fs):
    make_wo(client_for, fs, technician=str(fs["tech1"].id))
    body = client_for(fs["ops"]).get("/api/v1/dashboard/summary/").json()
    assert body["technicians_available"] == 2 and body["active_work_orders"] == 1
    tech_view = client_for(fs["t2"]).get("/api/v1/dashboard/summary/").json()
    assert tech_view["technicians_available"] is None and tech_view["active_work_orders"] == 0
