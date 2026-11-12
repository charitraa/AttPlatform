"""
Demo field-service data: technicians (with skills, certifications, shifts, time
off, service areas and home bases), and work orders in every state with
appointments this week. Work orders are driven through the real services, so
status logs, audit entries and ticket notes are genuine.

    python manage.py seed_field_service [--org acme]

Run after `seed_demo` and `seed_tickets`. Refuses to run in production.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.field_service import services
from apps.field_service.models import (
    ServiceArea,
    Skill,
    Technician,
    TechnicianAvailability,
    TechnicianCertification,
    TechnicianSkill,
    WorkOrder,
)
from apps.organizations.catalog import RoleCode
from apps.organizations.models import Membership, Organization
from apps.organizations.services import get_system_role
from apps.organizations.tenancy import TenantContext, permissions_for
from apps.tickets.models import Ticket, TicketCategory

User = get_user_model()
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82"
)
CITIES = {
    "Kathmandu": (Decimal("27.717200"), Decimal("85.324000")),
    "Lalitpur": (Decimal("27.664400"), Decimal("85.318800")),
    "Bhaktapur": (Decimal("27.671000"), Decimal("85.429800")),
    "Pokhara": (Decimal("28.209600"), Decimal("83.985600")),
    "Chitwan": (Decimal("27.529100"), Decimal("84.354200")),
}
TECHS = [
    # email, first, last, home city, skills {name: level}
    ("tech@acme.test", "Tariq", "Tech", "Kathmandu", {"HVAC": 5, "Refrigeration": 4, "Electrical": 2}),
    ("tina@acme.test", "Tina", "Gurung", "Pokhara", {"HVAC": 3, "Electrical": 4}),
    ("bikash@acme.test", "Bikash", "Shrestha", "Lalitpur", {"Network": 5, "Printers": 4, "Access control": 3}),
    ("sita@acme.test", "Sita", "Rai", "Chitwan", {"Refrigeration": 5, "Medical equipment": 4, "Electrical": 3}),
]
SKILL_CATEGORY = {"HVAC": "HVAC", "Refrigeration": "Refrigeration", "Electrical": "Electrical", "Network": "Network",
                  "Printers": "Printers", "Access control": "Access control", "Medical equipment": "Medical equipment"}


class Command(BaseCommand):
    help = "Seed demo technicians and work orders (development only)."

    def add_arguments(self, parser):
        parser.add_argument("--org", default="acme")
        parser.add_argument("--password", default="Demo!Pass2026")

    @transaction.atomic
    def handle(self, *args, org, password, **options):
        if settings.ENVIRONMENT == "production":
            raise CommandError("seed_field_service must not run in production.")
        try:
            organization = Organization.objects.get(slug=org)
        except Organization.DoesNotExist as exc:
            raise CommandError(f"Organization '{org}' not found. Run `manage.py seed_demo` first.") from exc
        if WorkOrder.objects.filter(organization=organization).exists():
            self.stdout.write(self.style.WARNING("Work orders already exist; nothing to do."))
            return
        tz = ZoneInfo(organization.timezone or "UTC")

        areas = {
            name: ServiceArea.objects.get_or_create(organization=organization, name=name,
                                                    defaults={"cities": cities})[0]
            for name, cities in (("Kathmandu Valley", ["Kathmandu", "Lalitpur", "Bhaktapur"]),
                                 ("Western", ["Pokhara"]), ("Central Terai", ["Chitwan"]))
        }
        skills = {}
        for name, category_name in SKILL_CATEGORY.items():
            skill, _ = Skill.objects.get_or_create(organization=organization, name=name,
                                                   defaults={"category": "Trade"})
            cat = TicketCategory.objects.filter(organization=organization, name=category_name).first()
            if cat:
                skill.ticket_categories.add(cat)
            skills[name] = skill

        role = get_system_role(RoleCode.FIELD_TECHNICIAN)
        techs = []
        monday = date.today() - timedelta(days=date.today().weekday())
        for email, first, last, city, levels in TECHS:
            user, created = User.objects.get_or_create(email=email, defaults={"first_name": first, "last_name": last})
            if created:
                user.set_password(password)
                user.save()
            Membership.objects.update_or_create(user=user, organization=organization,
                                                defaults={"role": role, "is_active": True})
            tech = Technician.objects.get(organization=organization, user=user)  # created by the membership signal
            tech.home_lat, tech.home_lng = CITIES[city]
            tech.employee_id = f"T-{len(techs) + 101}"
            tech.hourly_cost, tech.currency, tech.max_daily_jobs = Decimal("1200.00"), "NPR", 4
            tech.save()
            area = next(a for a in areas.values() if city in a.cities)
            tech.service_areas.add(area)
            for skill_name, level in levels.items():
                TechnicianSkill.objects.update_or_create(technician=tech, skill=skills[skill_name],
                                                         defaults={"level": level})
            TechnicianCertification.objects.get_or_create(
                technician=tech, name=f"{next(iter(levels))} technician certificate",
                defaults={"issuer": "CTEVT", "issued_at": date.today() - timedelta(days=700),
                          "expires_at": date.today() + timedelta(days=400 if len(techs) != 2 else -10)},
            )
            for d in range(10):  # two working weeks of 09:00-17:00 shifts, Sunday-Friday (Nepal)
                day = monday + timedelta(days=d - 1)
                if day.weekday() == 5:  # Saturday is the weekly holiday
                    continue
                TechnicianAvailability.objects.create(
                    technician=tech, type=TechnicianAvailability.Type.SHIFT,
                    starts_at=datetime.combine(day, time(9), tz), ends_at=datetime.combine(day, time(17), tz))
            techs.append(tech)
        # One technician takes Thursday off.
        thursday = monday + timedelta(days=3)
        TechnicianAvailability.objects.create(
            technician=techs[1], type=TechnicianAvailability.Type.TIME_OFF, note="Family event",
            starts_at=datetime.combine(thursday, time(0), tz), ends_at=datetime.combine(thursday, time(23, 59), tz))

        ops = Membership.objects.filter(organization=organization, role__code=RoleCode.OPS_MANAGER).first() or \
            Membership.objects.filter(organization=organization, role__code=RoleCode.ORG_ADMIN).first()
        dispatcher = TenantContext(membership=ops, permissions=permissions_for(ops))

        def tech_ctx(tech):
            m = Membership.objects.get(organization=organization, user=tech.user)
            return TenantContext(membership=m, permissions=permissions_for(m))

        field_tickets = list(
            Ticket.objects.filter(organization=organization, category__name__in=SKILL_CATEGORY.values())
            .select_related("customer", "category").order_by("created_at")[:12]
        )
        plan = ["completed", "completed", "completed", "in_progress", "on_site", "en_route", "accepted", "assigned",
                "assigned", "assigned", "created", "cancelled"]
        steps = ["accepted", "en_route", "on_site", "in_progress", "completed"]
        created = 0
        for i, (ticket, target) in enumerate(zip(field_tickets, plan, strict=False)):
            lat, lng = CITIES.get(ticket.customer.city, CITIES["Kathmandu"])
            wo = services.create_work_order(tenant=dispatcher, data={"ticket": ticket, "lat": lat, "lng": lng})
            created += 1
            if target == "created":
                continue
            from apps.field_service.selectors import rank_technicians

            best = rank_technicians(organization, category_id=ticket.category_id, lat=lat, lng=lng, limit=1)
            tech = Technician.objects.get(pk=best[0].technician_id) if best else techs[i % len(techs)]
            wo = services.assign_technician(tenant=dispatcher, work_order=wo, technician=tech)
            day = monday + timedelta(days=(i % 5))
            if day == thursday and tech == techs[1]:
                day += timedelta(days=1)
            start = datetime.combine(day, time(9 + (i % 3) * 2), tz)
            try:
                services.schedule(tenant=dispatcher, work_order=wo, starts_at=start, ends_at=start + timedelta(hours=2))
            except Exception as exc:  # noqa: BLE001 - demo data: skip slots that clash
                self.stdout.write(f"  skipped scheduling {wo.reference}: {exc}")
            if target == "cancelled":
                services.cancel(tenant=dispatcher, work_order=wo, reason="Customer resolved it remotely.")
                continue
            ctx = tech_ctx(tech)
            for step in steps[: steps.index(target) + 1] if target in steps else []:
                if step == "on_site":
                    services.add_evidence(tenant=ctx, work_order=wo, kind="before_photo",
                                          upload=SimpleUploadedFile("before.png", PNG), caption="Unit on arrival")
                if step == "completed":
                    services.add_evidence(tenant=ctx, work_order=wo, kind="after_photo",
                                          upload=SimpleUploadedFile("after.png", PNG), caption="Running normally")
                    wo = services.advance(tenant=ctx, work_order=wo, to_status=step, completion={
                        "completion_summary": "Diagnosed the fault, replaced the failed component and tested.",
                        "parts_used": [{"name": "Replacement part", "quantity": 1, "unit_cost": "850.00"}],
                        "labor_minutes": 75,
                    })
                    if i < 2:
                        services.confirm(tenant=ctx, work_order=wo, signed_by=ticket.contact.name if ticket.contact
                                         else "Site manager", rating=5 - i, comment="Quick and tidy work.")
                else:
                    wo = services.advance(tenant=ctx, work_order=wo, to_status=step)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(techs)} technicians, {len(skills)} skills, {len(areas)} service areas and "
            f"{created} work orders for '{organization.slug}'. Technician password: {password}"))
