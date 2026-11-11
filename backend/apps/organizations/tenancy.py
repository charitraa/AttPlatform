"""
Organization context resolution.

The active organization is ALWAYS derived from the authenticated user's
memberships. Clients with several memberships may send `X-Organization: <slug>`
to choose one; the slug is only honoured if the user has an active membership
there. Organization IDs in request bodies are never trusted.
"""
from dataclasses import dataclass, field

from rest_framework import exceptions

from .catalog import PERMISSIONS, RoleCode
from .models import Membership

ORG_HEADER = "HTTP_X_ORGANIZATION"


class NoOrganization(exceptions.PermissionDenied):
    default_code = "no_organization"
    default_detail = "You are not an active member of any organization."


@dataclass
class TenantContext:
    membership: Membership
    permissions: frozenset[str] = field(default_factory=frozenset)

    @property
    def organization(self):
        return self.membership.organization

    @property
    def role_code(self) -> str:
        return self.membership.role.code


def permissions_for(membership: Membership) -> frozenset[str]:
    if membership.role.code == RoleCode.SUPER_ADMIN:
        return frozenset(PERMISSIONS)
    return frozenset(membership.role.permissions.values_list("code", flat=True))


def active_memberships(user):
    return (
        Membership.objects.filter(user=user, is_active=True, organization__is_active=True)
        .select_related("organization", "role")
        .order_by("created_at")
    )


def resolve_tenant(request) -> TenantContext:
    user = request.user
    memberships = active_memberships(user)
    slug = request.META.get(ORG_HEADER, "").strip()
    membership = memberships.filter(organization__slug=slug).first() if slug else memberships.first()
    if membership is None:
        if slug and memberships.exists():
            # Don't reveal whether the organization exists.
            raise exceptions.PermissionDenied("You are not a member of the requested organization.")
        raise NoOrganization()
    return TenantContext(membership=membership, permissions=permissions_for(membership))


def attach_tenant(request) -> None:
    """Populate request.tenant / request.organization / request.membership (idempotent)."""
    if getattr(request, "tenant", None) is not None:
        return
    ctx = resolve_tenant(request)
    request.tenant = ctx
    request.organization = ctx.organization
    request.membership = ctx.membership
    # DRF wraps the Django request; mirror onto it so middleware/audit see the org too.
    django_request = getattr(request, "_request", None)
    if django_request is not None:
        django_request.organization = ctx.organization
