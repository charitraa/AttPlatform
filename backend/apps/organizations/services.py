"""Write-side business logic for organizations, memberships, roles and invitations."""
import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import exceptions

from apps.audit import services as audit
from apps.core.email import queue_email
from apps.core.exceptions import Conflict, DomainError

from .catalog import PERMISSIONS, SYSTEM_ROLES, RoleCode, role_rank
from .models import Invitation, Membership, Organization, Permission, Role, RolePermission

User = get_user_model()


# --------------------------------------------------------------------------- roles
def sync_roles_and_permissions() -> None:
    """Make Permission/Role/RolePermission rows match catalog.py. Idempotent."""
    with transaction.atomic():
        for code, description in PERMISSIONS.items():
            Permission.objects.update_or_create(code=code, defaults={"description": description})
        Permission.objects.exclude(code__in=PERMISSIONS.keys()).delete()
        perms = {p.code: p for p in Permission.objects.all()}

        for definition in SYSTEM_ROLES.values():
            role, _ = Role.objects.update_or_create(
                organization=None,
                code=definition.code,
                defaults={
                    "name": definition.name,
                    "description": definition.description,
                    "rank": definition.rank,
                    "is_system": True,
                },
            )
            current = set(role.permissions.values_list("code", flat=True))
            wanted = set(definition.permissions)
            RolePermission.objects.filter(role=role, permission__code__in=current - wanted).delete()
            RolePermission.objects.bulk_create(
                [RolePermission(role=role, permission=perms[c]) for c in wanted - current]
            )


def sync_roles_after_migrate(sender, using=None, **kwargs) -> None:
    sync_roles_and_permissions()


def get_system_role(code: str) -> Role:
    try:
        return Role.objects.get(organization=None, code=code)
    except Role.DoesNotExist as exc:
        raise exceptions.ValidationError({"role": [f"Unknown role '{code}'."]}) from exc


def assignable_role_codes(actor_membership: Membership) -> list[str]:
    """Roles an actor may grant: those at or below their own rank; Super Admin only by Super Admins."""
    actor_rank = role_rank(actor_membership.role.code)
    return [
        code
        for code, d in SYSTEM_ROLES.items()
        if d.rank <= actor_rank and (code != RoleCode.SUPER_ADMIN or actor_membership.is_super_admin)
    ]


def _ensure_can_grant(actor: Membership, role_code: str) -> None:
    if role_code not in assignable_role_codes(actor):
        raise exceptions.PermissionDenied("You cannot assign a role with higher privileges than your own.")


def _ensure_can_manage(actor: Membership, target: Membership) -> None:
    if target.user_id == actor.user_id:
        raise DomainError("You cannot change your own role or status.")
    if role_rank(target.role.code) > role_rank(actor.role.code):
        raise exceptions.PermissionDenied("You cannot manage a user with higher privileges than your own.")


def _ensure_admin_remains(organization: Organization, excluding: Membership) -> None:
    remaining = (
        Membership.objects.filter(
            organization=organization, is_active=True, role__code__in=[RoleCode.ORG_ADMIN, RoleCode.SUPER_ADMIN]
        )
        .exclude(pk=excluding.pk)
        .exists()
    )
    if not remaining:
        raise DomainError("The organization must keep at least one active administrator.")


# ------------------------------------------------------------------- organizations
def unique_slug(name: str) -> str:
    base = slugify(name)[:60] or "org"
    slug, n = base, 2
    while Organization.objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


@transaction.atomic
def register_organization(*, organization_name: str, email: str, password: str, first_name: str, last_name: str,
                          request=None):
    """Self-service sign-up: creates an organization and its first Organization Admin."""
    email = email.strip().lower()
    if User.objects.filter(email__iexact=email).exists():
        raise Conflict("An account with this email already exists.")
    user = User(email=email, first_name=first_name, last_name=last_name)
    validate_password(password, user)
    user.set_password(password)
    user.save()
    org = Organization.objects.create(name=organization_name, slug=unique_slug(organization_name))
    membership = Membership.objects.create(user=user, organization=org, role=get_system_role(RoleCode.ORG_ADMIN))
    audit.record("organization.registered", request=request, actor=user, organization=org, target=org)
    return user, membership


def update_organization(*, organization: Organization, data: dict, request) -> Organization:
    changes = {}
    for field in ("name", "timezone", "locale"):
        if field in data and getattr(organization, field) != data[field]:
            changes[field] = {"from": getattr(organization, field), "to": data[field]}
            setattr(organization, field, data[field])
    if "settings" in data:
        merged = {**organization.settings, **data["settings"]}
        if merged != organization.settings:
            changes["settings"] = {"from": organization.settings, "to": merged}
            organization.settings = merged
    if changes:
        organization.save()
        audit.record("organization.updated", request=request, target=organization, changes=changes)
    return organization


# --------------------------------------------------------------------- memberships
@transaction.atomic
def change_member(*, actor: Membership, target: Membership, role_code: str | None = None,
                  is_active: bool | None = None, request=None) -> Membership:
    target = Membership.objects.select_for_update().select_related("role", "user").get(pk=target.pk)
    _ensure_can_manage(actor, target)
    changes = {}

    if role_code is not None and role_code != target.role.code:
        _ensure_can_grant(actor, role_code)
        if target.role.code in (RoleCode.ORG_ADMIN, RoleCode.SUPER_ADMIN) and role_code not in (
            RoleCode.ORG_ADMIN, RoleCode.SUPER_ADMIN
        ):
            _ensure_admin_remains(target.organization, excluding=target)
        changes["role"] = {"from": target.role.code, "to": role_code}
        target.role = get_system_role(role_code)

    if is_active is not None and is_active != target.is_active:
        if not is_active and target.role.code in (RoleCode.ORG_ADMIN, RoleCode.SUPER_ADMIN):
            _ensure_admin_remains(target.organization, excluding=target)
        changes["is_active"] = {"from": target.is_active, "to": is_active}
        target.is_active = is_active

    if changes:
        target.save()
        action = "membership.role_changed" if "role" in changes else "membership.status_changed"
        audit.record(action, request=request, target=target, changes={**changes, "user": target.user.email})
        if "is_active" in changes and not is_active:
            from apps.accounts.services import revoke_all_refresh_tokens

            # Deactivated users lose their sessions immediately (if this was their only org).
            if not Membership.objects.filter(user=target.user, is_active=True).exists():
                revoke_all_refresh_tokens(target.user)
    return target


# --------------------------------------------------------------------- invitations
def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _send_invitation_email(invitation: Invitation, token: str) -> None:
    link = f"{settings.FRONTEND_URL.rstrip('/')}/accept-invite?token={token}"
    inviter = invitation.invited_by.full_name if invitation.invited_by else "An administrator"
    queue_email(
        to=invitation.email,
        subject=f"You're invited to join {invitation.organization.name} on ATT",
        body=(
            f"{inviter} invited you to join {invitation.organization.name} as {invitation.role.name}.\n\n"
            f"Accept the invitation: {link}\n\n"
            f"This link expires on {invitation.expires_at:%Y-%m-%d %H:%M} UTC. "
            "If you weren't expecting this, you can ignore this email."
        ),
    )


@transaction.atomic
def create_invitation(*, actor: Membership, email: str, role_code: str, request=None) -> Invitation:
    email = email.strip().lower()
    organization = actor.organization
    _ensure_can_grant(actor, role_code)
    if Membership.objects.filter(organization=organization, user__email__iexact=email).exists():
        raise Conflict("This person is already a member of the organization.")
    if Invitation.objects.filter(organization=organization, email=email,
                                 accepted_at__isnull=True, revoked_at__isnull=True).exists():
        raise Conflict("An invitation for this email is already open. Resend or revoke it instead.")

    token = secrets.token_urlsafe(32)
    invitation = Invitation.objects.create(
        organization=organization,
        email=email,
        role=get_system_role(role_code),
        token_hash=hash_token(token),
        expires_at=timezone.now() + timedelta(days=settings.INVITATION_EXPIRY_DAYS),
        invited_by=actor.user,
    )
    _send_invitation_email(invitation, token)
    audit.record("invitation.created", request=request, target=invitation, changes={"email": email, "role": role_code})
    return invitation


@transaction.atomic
def resend_invitation(*, invitation: Invitation, request=None) -> Invitation:
    if invitation.accepted_at or invitation.revoked_at:
        raise DomainError("Only open invitations can be resent.")
    token = secrets.token_urlsafe(32)  # rotate: the previous link stops working
    invitation.token_hash = hash_token(token)
    invitation.expires_at = timezone.now() + timedelta(days=settings.INVITATION_EXPIRY_DAYS)
    invitation.save(update_fields=["token_hash", "expires_at", "updated_at"])
    _send_invitation_email(invitation, token)
    audit.record("invitation.resent", request=request, target=invitation)
    return invitation


def revoke_invitation(*, invitation: Invitation, request=None) -> None:
    if invitation.accepted_at:
        raise DomainError("This invitation has already been accepted.")
    if not invitation.revoked_at:
        invitation.revoked_at = timezone.now()
        invitation.save(update_fields=["revoked_at", "updated_at"])
        audit.record("invitation.revoked", request=request, target=invitation)


class InvalidInvitation(exceptions.ValidationError):
    default_code = "invalid_invitation"


def get_pending_invitation(token: str) -> Invitation:
    invitation = (
        Invitation.objects.pending().select_related("organization", "role").filter(token_hash=hash_token(token)).first()
    )
    if invitation is None:
        raise InvalidInvitation({"token": ["This invitation link is invalid or has expired."]})
    return invitation


@transaction.atomic
def accept_invitation(*, token: str, password: str, first_name: str = "", last_name: str = "", request=None):
    invitation = get_pending_invitation(token)
    invitation = Invitation.objects.select_for_update().get(pk=invitation.pk)  # guard against double acceptance
    if invitation.accepted_at:
        raise InvalidInvitation({"token": ["This invitation link is invalid or has expired."]})

    user = User.objects.filter(email__iexact=invitation.email).first()
    if user is None:
        user = User(email=invitation.email, first_name=first_name, last_name=last_name,
                    email_verified_at=timezone.now())
        validate_password(password, user)
        user.set_password(password)
        user.save()
    elif not user.is_active or not user.check_password(password):
        # Existing account: prove ownership with its current password.
        raise exceptions.ValidationError({"password": ["Enter the current password for your existing account."]})

    membership, created = Membership.objects.get_or_create(
        user=user, organization=invitation.organization,
        defaults={"role": invitation.role, "invited_by": invitation.invited_by},
    )
    if not created:
        raise Conflict("You are already a member of this organization.")
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at", "updated_at"])
    audit.record("invitation.accepted", request=request, actor=user, organization=invitation.organization,
                 target=invitation)
    return user, membership
