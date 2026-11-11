"""
Demo service-desk data for local development: customers, contacts, assets,
categories and tickets in various lifecycle states.

    python manage.py seed_tickets [--org acme] [--count 40]

Tickets are created through the real services (so history and audit entries are
genuine), then `created_at`/lifecycle timestamps are back-dated across the last
30 days so dashboards have a realistic shape. Refuses to run in production.
"""

import random
from datetime import date, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.assets.models import Asset, AssetCategory
from apps.customers.models import Customer, CustomerContact
from apps.organizations.catalog import RoleCode
from apps.organizations.models import Membership, Organization
from apps.organizations.tenancy import TenantContext, permissions_for
from apps.tickets import services
from apps.tickets.models import Ticket, TicketCategory, TicketComment, TicketStatus

CUSTOMERS = [
    ("Himalayan Bank Ltd", "enterprise", "Kathmandu", "it.support@himalayanbank.test"),
    ("Everest Hotel & Spa", "premium", "Pokhara", "facilities@everesthotel.test"),
    ("Lalitpur Medical Centre", "enterprise", "Lalitpur", "biomed@lmc.test"),
    ("Bhaktapur Textiles", "standard", "Bhaktapur", "ops@bhaktapurtextiles.test"),
    ("Annapurna Cold Storage", "premium", "Chitwan", "plant@annapurnacold.test"),
    ("Sagarmatha School", "standard", "Kathmandu", "admin@sagarmatha-school.test"),
]
CATEGORIES = [
    ("HVAC", "Facilities", "high"),
    ("Electrical", "Facilities", "high"),
    ("Network", "IT", "medium"),
    ("Printers", "IT", "low"),
    ("Medical equipment", "Biomedical", "critical"),
    ("Refrigeration", "Facilities", "high"),
    ("Access control", "Security", "medium"),
]
ASSETS = [
    ("HVAC", "Rooftop AC unit", "Daikin", "VRV-IV"),
    ("Electrical", "Backup generator", "Cummins", "C150D5"),
    ("Network", "Core switch", "Cisco", "C9300-48P"),
    ("Printers", "Floor printer", "HP", "LaserJet M607"),
    ("Medical equipment", "Patient monitor", "Philips", "IntelliVue MX450"),
    ("Refrigeration", "Cold room compressor", "Bitzer", "4FES-5Y"),
    ("Access control", "Door controller", "HID", "VertX V1000"),
]
ISSUES = [
    (
        "HVAC",
        "AC not cooling in server room",
        "Temperature in the server room is 31°C and rising. Unit runs but blows warm air.",
    ),
    ("HVAC", "Strange noise from rooftop unit", "Loud rattling noise from the rooftop unit since this morning."),
    (
        "Electrical",
        "Generator failed weekly test",
        "Generator did not start during the scheduled Monday test. Battery light on.",
    ),
    (
        "Electrical",
        "Frequent power trips on floor 2",
        "Breaker for floor 2 trips several times a day, mostly around noon.",
    ),
    ("Network", "Branch office offline", "The whole branch lost network connectivity. Switch lights are amber."),
    ("Network", "Slow Wi-Fi in conference rooms", "Video calls drop in both conference rooms. Other areas seem fine."),
    (
        "Printers",
        "Printer jamming on every job",
        "Floor printer jams on almost every print job since the toner was replaced.",
    ),
    ("Printers", "Scan to email not working", "Scanned documents never arrive in mailboxes. No error on the device."),
    (
        "Medical equipment",
        "Patient monitor showing SpO2 error",
        "Monitor in ward 3 shows 'SpO2 probe off' even with a new probe.",
    ),
    (
        "Refrigeration",
        "Cold room temperature alarm",
        "Cold room alarm triggered at 2am, temperature reached 9°C. Stock at risk.",
    ),
    ("Refrigeration", "Compressor short cycling", "Compressor turns on and off every few minutes."),
    (
        "Access control",
        "Badge reader rejecting valid cards",
        "Main entrance reader rejects several valid staff badges.",
    ),
]


class Command(BaseCommand):
    help = "Seed demo customers, assets and tickets (development only)."

    def add_arguments(self, parser):
        parser.add_argument("--org", default="acme")
        parser.add_argument("--count", type=int, default=40)
        parser.add_argument("--seed", type=int, default=7, help="Random seed for repeatable data")

    @transaction.atomic
    def handle(self, *args, org: str, count: int, seed: int, **options):
        if settings.ENVIRONMENT == "production":
            raise CommandError("seed_tickets must not run in production.")
        rng = random.Random(seed)  # noqa: S311 - demo data, not security-sensitive
        try:
            organization = Organization.objects.get(slug=org)
        except Organization.DoesNotExist as exc:
            raise CommandError(f"Organization '{org}' not found. Run `manage.py seed_demo` first.") from exc
        if Ticket.objects.filter(organization=organization).exists():
            self.stdout.write(self.style.WARNING("Tickets already exist for this organization; nothing to do."))
            return

        members = Membership.objects.filter(organization=organization, is_active=True).select_related("user", "role")
        by_role = {}
        for m in members:
            by_role.setdefault(m.role.code, []).append(m)
        agents = by_role.get(RoleCode.SUPPORT_AGENT, []) + by_role.get(RoleCode.OPS_MANAGER, [])
        technicians = by_role.get(RoleCode.FIELD_TECHNICIAN, [])
        if not agents:
            raise CommandError("No support agents found. Run `manage.py seed_demo` first.")

        categories = {
            name: TicketCategory.objects.get_or_create(
                organization=organization,
                name=name,
                parent=None,
                defaults={"department": dept, "default_priority": prio},
            )[0]
            for name, dept, prio in CATEGORIES
        }
        asset_categories = {
            name: AssetCategory.objects.get_or_create(organization=organization, name=name)[0]
            for name, *_ in CATEGORIES
        }

        customers = []
        for i, (name, tier, city, email) in enumerate(CUSTOMERS):
            customer, _ = Customer.objects.get_or_create(
                organization=organization,
                name=name,
                defaults={"tier": tier, "city": city, "country": "NP", "email": email, "phone": f"+977-1-55{i:05d}"},
            )
            CustomerContact.objects.get_or_create(
                customer=customer,
                name=f"{city} Facilities Lead",
                defaults={"email": f"lead@{email.split('@')[1]}", "is_primary": True, "job_title": "Facilities lead"},
            )
            customers.append(customer)

        # Link the demo customer-portal user to the first customer account.
        portal = by_role.get(RoleCode.CUSTOMER, [])
        if portal:
            CustomerContact.objects.get_or_create(
                customer=customers[0],
                user=portal[0].user,
                defaults={"name": portal[0].user.full_name, "email": portal[0].user.email, "job_title": "IT officer"},
            )

        assets = {}
        for c_idx, customer in enumerate(customers):
            for a_idx, (cat, name, make, model) in enumerate(ASSETS):
                if rng.random() < 0.55:
                    installed = date.today() - timedelta(days=rng.randint(200, 2000))
                    assets.setdefault((customer.id, cat), []).append(
                        Asset.objects.create(
                            organization=organization,
                            customer=customer,
                            category=asset_categories[cat],
                            asset_tag=f"AST-{c_idx + 1:02d}{a_idx + 1:02d}",
                            name=name,
                            manufacturer=make,
                            model=model,
                            serial_number=f"SN{rng.randint(10**7, 10**8 - 1)}",
                            location=f"Building {rng.choice('ABC')}",
                            installed_at=installed,
                            warranty_expires_at=installed + timedelta(days=rng.choice([365, 730, 1095])),
                        )
                    )

        admin = (by_role.get(RoleCode.ORG_ADMIN) or agents)[0]
        tenant = TenantContext(membership=admin, permissions=permissions_for(admin))
        agent_tenants = [TenantContext(membership=a, permissions=permissions_for(a)) for a in agents]
        now = timezone.now()
        # Weighted outcome per ticket age: older tickets are more likely to be finished.
        for _ in range(count):
            cat_name, title, description = rng.choice(ISSUES)
            customer = rng.choice(customers)
            asset_choices = assets.get((customer.id, cat_name), [])
            ticket = services.create_ticket(
                tenant=tenant,
                data={
                    "title": title,
                    "description": description,
                    "customer": customer,
                    "contact": customer.contacts.filter(is_primary=True).first(),
                    "asset": rng.choice(asset_choices) if asset_choices else None,
                    "category": categories[cat_name],
                    "priority": rng.choices(["low", "medium", "high", "critical"], weights=[2, 5, 3, 1])[0],
                    "channel": rng.choice(["email", "phone", "portal", "staff"]),
                },
            )
            age_days = rng.uniform(0, 29)
            agent_tenant = rng.choice(agent_tenants)
            outcome = rng.random() * (1 + age_days / 15)
            if outcome > 0.35:
                services.assign_ticket(
                    tenant=tenant,
                    ticket=ticket,
                    agent_id=agent_tenant.membership.user_id,
                    technician_id=rng.choice(technicians).user_id
                    if technicians and cat_name != "Network" and rng.random() < 0.5
                    else services.UNSET,
                )
                services.add_comment(
                    tenant=agent_tenant,
                    ticket=ticket,
                    visibility=TicketComment.Visibility.PUBLIC,
                    body="Thanks for reporting this. We're looking into it and will update you shortly.",
                )
            if outcome > 0.6:
                services.transition_ticket(tenant=agent_tenant, ticket=ticket, to_status=TicketStatus.IN_PROGRESS)
                services.add_comment(
                    tenant=agent_tenant,
                    ticket=ticket,
                    visibility=TicketComment.Visibility.INTERNAL,
                    body="Checked remotely; likely needs an on-site visit.",
                )
            if outcome > 0.95:
                services.transition_ticket(
                    tenant=agent_tenant,
                    ticket=ticket,
                    to_status=TicketStatus.RESOLVED,
                    resolution_notes="Replaced the faulty component and verified normal operation.",
                )
            if outcome > 1.4:
                services.transition_ticket(tenant=agent_tenant, ticket=ticket, to_status=TicketStatus.CLOSED)
            elif 0.75 < outcome < 0.85:
                services.escalate_ticket(tenant=agent_tenant, ticket=ticket, reason="Needs vendor involvement.")

            # Back-date so the dashboard has a realistic 30-day shape.
            created = now - timedelta(days=age_days)
            ticket.refresh_from_db()
            fields = {"created_at": created}
            if ticket.first_response_at:
                fields["first_response_at"] = created + timedelta(minutes=rng.randint(10, 240))
            if ticket.resolved_at:
                fields["resolved_at"] = min(now, created + timedelta(hours=rng.randint(2, 96)))
            if ticket.closed_at:
                fields["closed_at"] = min(now, fields["resolved_at"] + timedelta(hours=rng.randint(1, 48)))
            fields["due_at"] = created + timedelta(
                hours={"critical": 8, "high": 24, "medium": 72, "low": 120}[ticket.priority]
            )
            Ticket.objects.filter(pk=ticket.pk).update(**fields)
            ticket.history.update(created_at=created)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(customers)} customers, {sum(len(v) for v in assets.values())} assets, "
                f"{len(categories)} categories and {count} tickets for '{organization.slug}'."
            )
        )
