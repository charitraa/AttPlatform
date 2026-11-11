"""
Create demo organizations and one user per role for local development.

    python manage.py seed_demo [--password ...]

Idempotent: re-running updates roles/passwords instead of duplicating rows.
Refuses to run when ENVIRONMENT=production.
"""
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.organizations.catalog import RoleCode
from apps.organizations.models import Membership, Organization
from apps.organizations.services import get_system_role, sync_roles_and_permissions

User = get_user_model()

DEMO_ORGS = [
    {
        "name": "Acme Facilities", "slug": "acme", "timezone": "Asia/Kathmandu",
        "users": [
            ("superadmin@att.local", "Sam", "Root", RoleCode.SUPER_ADMIN),
            ("admin@acme.test", "Alice", "Admin", RoleCode.ORG_ADMIN),
            ("ops@acme.test", "Omar", "Ops", RoleCode.OPS_MANAGER),
            ("agent@acme.test", "Ana", "Agent", RoleCode.SUPPORT_AGENT),
            ("tech@acme.test", "Tariq", "Tech", RoleCode.FIELD_TECHNICIAN),
            ("customer@acme.test", "Cara", "Customer", RoleCode.CUSTOMER),
        ],
    },
    {
        # A second tenant, useful for checking organization isolation by hand.
        "name": "Globex Services", "slug": "globex", "timezone": "UTC",
        "users": [("admin@globex.test", "Gina", "Globex", RoleCode.ORG_ADMIN)],
    },
]


class Command(BaseCommand):
    help = "Seed demo organizations and users (development only)."

    def add_arguments(self, parser):
        parser.add_argument("--password", default=os.environ.get("DEMO_PASSWORD", "Demo!Pass2026"))

    @transaction.atomic
    def handle(self, *args, password: str, **options):
        if settings.ENVIRONMENT == "production":
            raise CommandError("seed_demo must not run in production.")
        sync_roles_and_permissions()
        rows = []
        for spec in DEMO_ORGS:
            org, _ = Organization.objects.update_or_create(
                slug=spec["slug"], defaults={"name": spec["name"], "timezone": spec["timezone"]}
            )
            for email, first, last, role_code in spec["users"]:
                user, _ = User.objects.get_or_create(email=email, defaults={"first_name": first, "last_name": last})
                user.set_password(password)
                if role_code == RoleCode.SUPER_ADMIN:
                    user.is_staff = user.is_superuser = True  # Django admin access for the platform operator
                user.save()
                Membership.objects.update_or_create(
                    user=user, organization=org, defaults={"role": get_system_role(role_code), "is_active": True}
                )
                rows.append((org.slug, role_code, email))

        self.stdout.write(self.style.SUCCESS(f"Seeded {len(rows)} demo users (password: {password})"))
        for slug, role, email in rows:
            self.stdout.write(f"  {slug:<8} {role:<17} {email}")
