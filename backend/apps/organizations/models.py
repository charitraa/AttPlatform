from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import BaseModel

from .catalog import RoleCode


class Organization(BaseModel):
    """A tenant. Every tenant-owned row in the system references one."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True)
    timezone = models.CharField(max_length=64, default="UTC")
    locale = models.CharField(max_length=16, default="en")
    # Operational settings (validated by OrganizationSettingsSerializer), e.g.
    # {"routing_policy": "recommend", "ai_enabled": true, "ticket_auto_close_days": 7}
    settings = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Permission(models.Model):
    """A `<resource>.<action>` permission code. Mirrors `catalog.PERMISSIONS`."""

    code = models.CharField(max_length=64, unique=True)
    description = models.CharField(max_length=255)

    class Meta:
        ordering = ("code",)

    def __str__(self) -> str:
        return self.code

    @property
    def module(self) -> str:
        return self.code.split(".", 1)[0]


class Role(BaseModel):
    """
    System roles have `organization=NULL` and are shared by all tenants. The schema
    allows organization-specific custom roles later without migration.
    """

    organization = models.ForeignKey(
        Organization, null=True, blank=True, on_delete=models.CASCADE, related_name="roles"
    )
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    rank = models.PositiveSmallIntegerField(default=0)
    is_system = models.BooleanField(default=False)
    permissions = models.ManyToManyField(Permission, through="RolePermission", related_name="roles")

    class Meta:
        ordering = ("-rank", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "code"), name="uniq_role_code_per_org", nulls_distinct=False
            ),
        ]

    def __str__(self) -> str:
        return self.name


class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("role", "permission"), name="uniq_role_permission")]

    def __str__(self) -> str:
        return f"{self.role_id}:{self.permission_id}"


class Membership(BaseModel):
    """Links a user to an organization with exactly one role."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="memberships")
    is_active = models.BooleanField(default=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ("created_at",)
        constraints = [models.UniqueConstraint(fields=("user", "organization"), name="uniq_membership")]
        indexes = [models.Index(fields=("organization", "is_active"))]

    def __str__(self) -> str:
        return f"{self.user} @ {self.organization} ({self.role.code})"

    @property
    def is_super_admin(self) -> bool:
        return self.role.code == RoleCode.SUPER_ADMIN


class InvitationQuerySet(models.QuerySet):
    def pending(self):
        return self.filter(accepted_at__isnull=True, revoked_at__isnull=True, expires_at__gt=timezone.now())


class Invitation(BaseModel):
    """
    The raw token is only ever sent in the invitation email; the database stores
    its SHA-256 hash, so a database leak does not expose usable invitation links.
    """

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="+")
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    objects = InvitationQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            # At most one open invitation per email per organization.
            models.UniqueConstraint(
                fields=("organization", "email"),
                condition=Q(accepted_at__isnull=True, revoked_at__isnull=True),
                name="uniq_open_invitation",
            ),
        ]

    @property
    def status(self) -> str:
        if self.accepted_at:
            return "accepted"
        if self.revoked_at:
            return "revoked"
        if self.expires_at <= timezone.now():
            return "expired"
        return "pending"
