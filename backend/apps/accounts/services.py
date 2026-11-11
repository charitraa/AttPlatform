"""Authentication, session (token) management and password flows."""
import logging

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import exceptions
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from apps.audit import services as audit
from apps.core.email import queue_email
from apps.organizations.tenancy import active_memberships

logger = logging.getLogger(__name__)
User = get_user_model()


class InvalidCredentials(exceptions.AuthenticationFailed):
    default_code = "invalid_credentials"
    default_detail = "Invalid email or password."


# ---------------------------------------------------------------------- sessions
def login(*, email: str, password: str, request=None):
    """
    Returns (user, refresh_token). A single generic error covers unknown email,
    wrong password, inactive user and no active membership — no account enumeration.
    """
    email = email.strip().lower()
    user = authenticate(request=request, email=email, password=password)
    if user is None or not active_memberships(user).exists():
        audit.record("auth.login_failed", request=request, changes={"email": email})
        raise InvalidCredentials()
    refresh = RefreshToken.for_user(user)
    user.last_login = refresh.current_time
    user.save(update_fields=["last_login"])
    audit.record("auth.login", request=request, actor=user, organization=active_memberships(user).first().organization)
    return user, refresh


def rotate_refresh(raw_refresh: str) -> tuple[str, str]:
    """Validate + rotate a refresh token (old one is blacklisted). Returns (access, new_refresh)."""
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.serializers import TokenRefreshSerializer

    serializer = TokenRefreshSerializer(data={"refresh": raw_refresh})
    try:
        serializer.is_valid(raise_exception=True)
    except (TokenError, exceptions.ValidationError, exceptions.AuthenticationFailed, User.DoesNotExist) as exc:
        raise exceptions.AuthenticationFailed("Your session has expired. Please sign in again.",
                                              code="session_expired") from exc
    data = serializer.validated_data
    # Refuse refresh for users who were deactivated or lost every membership since login.
    user_id = RefreshToken(data["refresh"]).payload.get(settings.SIMPLE_JWT.get("USER_ID_CLAIM", "user_id"))
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None or not active_memberships(user).exists():
        revoke_refresh(data["refresh"])
        raise exceptions.AuthenticationFailed("Your session has expired. Please sign in again.",
                                              code="session_expired")
    return data["access"], data["refresh"]


def revoke_refresh(raw_refresh: str | None) -> None:
    if not raw_refresh:
        return
    try:
        RefreshToken(raw_refresh).blacklist()
    except Exception as exc:  # already invalid/expired/blacklisted: logout still succeeds
        logger.debug("Refresh token not blacklisted: %s", exc.__class__.__name__)


def revoke_all_refresh_tokens(user) -> int:
    tokens = OutstandingToken.objects.filter(user=user).exclude(blacklistedtoken__isnull=False)
    created = BlacklistedToken.objects.bulk_create(
        [BlacklistedToken(token=t) for t in tokens], ignore_conflicts=True
    )
    return len(created)


# --------------------------------------------------------------------- passwords
def request_password_reset(*, email: str, request=None) -> None:
    """Always succeeds from the caller's perspective (no account enumeration)."""
    user = User.objects.filter(email__iexact=email.strip(), is_active=True).first()
    if user is None or not user.has_usable_password():
        audit.record("auth.password_reset_requested_unknown", request=request, changes={"email": email.lower()})
        return
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?uid={uid}&token={token}"
    minutes = settings.PASSWORD_RESET_TIMEOUT // 60
    queue_email(
        to=user.email,
        subject="Reset your ATT password",
        body=(
            f"Hi {user.get_short_name()},\n\nUse this link to choose a new password: {link}\n\n"
            f"The link expires in {minutes} minutes and can be used once. "
            "If you didn't ask for this, you can ignore this email."
        ),
    )
    audit.record("auth.password_reset_requested", request=request, actor=user, target=user)


def _user_from_uid(uid: str):
    try:
        return User.objects.get(pk=force_str(urlsafe_base64_decode(uid)), is_active=True)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        return None


@transaction.atomic
def reset_password(*, uid: str, token: str, new_password: str, request=None) -> None:
    user = _user_from_uid(uid)
    # The token embeds the password hash and last_login, so it is single-use.
    if user is None or not default_token_generator.check_token(user, token):
        raise exceptions.ValidationError({"token": ["This reset link is invalid or has expired."]},
                                         code="invalid_reset_token")
    validate_password(new_password, user)
    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    revoke_all_refresh_tokens(user)
    audit.record("auth.password_reset", request=request, actor=user, target=user)


@transaction.atomic
def change_password(*, user, current_password: str, new_password: str, request=None) -> RefreshToken:
    """Changes the password, signs out every other session and returns a fresh refresh token."""
    if not user.check_password(current_password):
        raise exceptions.ValidationError({"current_password": ["Your current password is incorrect."]})
    validate_password(new_password, user)
    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    revoke_all_refresh_tokens(user)
    audit.record("auth.password_changed", request=request, actor=user, target=user)
    return RefreshToken.for_user(user)


def update_profile(*, user, data: dict, request=None):
    changes = {f: {"from": getattr(user, f), "to": v} for f, v in data.items() if getattr(user, f) != v}
    if changes:
        for field, value in data.items():
            setattr(user, field, value)
        user.save(update_fields=[*data.keys(), "updated_at"])
        audit.record("user.profile_updated", request=request, actor=user, target=user, changes=changes)
    return user
