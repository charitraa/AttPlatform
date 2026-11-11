import re

import pytest
from django.conf import settings
from django.core import mail
from django.urls import reverse

from apps.audit.models import AuditLog
from conftest import PASSWORD

pytestmark = pytest.mark.django_db
COOKIE = settings.REFRESH_COOKIE_NAME


def login(client, email, password=PASSWORD):
    return client.post(reverse("auth-login"), {"email": email, "password": password}, format="json")


# ------------------------------------------------------------------------- login
def test_login_returns_access_token_and_sets_httponly_refresh_cookie(api_client, admin):
    response = login(api_client, "ADMIN@acme.test")  # email is case-insensitive
    assert response.status_code == 200
    body = response.json()
    assert body["access"]
    assert body["user"]["email"] == "admin@acme.test"
    assert body["user"]["role"]["code"] == "org_admin"
    assert "users.manage" in body["user"]["permissions"]
    assert body["user"]["organization"]["slug"] == admin.organization.slug

    cookie = response.cookies[COOKIE]
    assert cookie["httponly"]
    assert cookie["path"] == "/api/v1/auth/"
    assert cookie["samesite"] == "Strict"
    assert "refresh" not in body  # the refresh token is never exposed to scripts


@pytest.mark.parametrize("email,password", [("admin@acme.test", "wrong-password"), ("nobody@acme.test", PASSWORD)])
def test_login_failure_is_generic_and_audited(api_client, admin, email, password):
    response = login(api_client, email, password)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert AuditLog.objects.filter(action="auth.login_failed", changes__email=email).exists()


def test_login_rejected_without_active_membership(api_client, org, make_member):
    member = make_member(org, is_active=False)
    assert login(api_client, member.user.email).status_code == 401


def test_login_rejected_for_inactive_user(api_client, admin):
    admin.user.is_active = False
    admin.user.save()
    assert login(api_client, admin.user.email).status_code == 401


def test_login_is_throttled(api_client, admin):
    codes = [login(api_client, "admin@acme.test", "bad").status_code for _ in range(6)]
    assert codes[:5] == [401] * 5
    assert codes[5] == 429
    assert login(api_client, "admin@acme.test", "bad").json()["error"]["code"] == "throttled"


# ----------------------------------------------------------------- refresh/logout
def test_refresh_rotates_cookie_and_old_token_is_rejected(api_client, admin):
    old = login(api_client, admin.user.email).cookies[COOKIE].value
    response = api_client.post(reverse("auth-refresh"))
    assert response.status_code == 200
    assert response.json()["access"]
    new = response.cookies[COOKIE].value
    assert new and new != old

    api_client.cookies[COOKIE] = old  # replaying the rotated token fails
    replay = api_client.post(reverse("auth-refresh"))
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "session_expired"


def test_refresh_without_cookie_is_unauthenticated(api_client):
    assert api_client.post(reverse("auth-refresh")).status_code == 401


def test_logout_revokes_refresh_token(api_client, admin):
    login(api_client, admin.user.email)
    token = api_client.cookies[COOKIE].value
    response = api_client.post(reverse("auth-logout"))
    assert response.status_code == 204
    assert response.cookies[COOKIE].value == ""  # cookie cleared
    api_client.cookies[COOKIE] = token
    assert api_client.post(reverse("auth-refresh")).status_code == 401


def test_refresh_fails_after_membership_deactivated(api_client, admin, make_member):
    member = make_member(admin.organization)
    login(api_client, member.user.email)
    member.is_active = False
    member.save()
    assert api_client.post(reverse("auth-refresh")).status_code == 401


# ---------------------------------------------------------------------------- me
def test_me_requires_authentication(api_client):
    assert api_client.get(reverse("me")).status_code == 401


def test_me_returns_profile_and_context(client_for, admin):
    body = client_for(admin).get(reverse("me")).json()
    assert body["email"] == admin.user.email
    assert body["role"] == {"code": "org_admin", "name": "Organization Admin"}
    assert len(body["memberships"]) == 1


def test_update_profile(client_for, admin):
    client = client_for(admin)
    response = client.patch(reverse("me"), {"first_name": "Alicia", "timezone": "Asia/Kathmandu"}, format="json")
    assert response.status_code == 200
    assert response.json()["first_name"] == "Alicia"
    assert response.json()["timezone"] == "Asia/Kathmandu"
    assert AuditLog.objects.filter(action="user.profile_updated", actor=admin.user).exists()


def test_profile_cannot_change_email_or_flags(client_for, admin):
    client_for(admin).patch(reverse("me"), {"email": "evil@x.test", "is_staff": True}, format="json")
    admin.user.refresh_from_db()
    assert admin.user.email == "admin@acme.test"
    assert admin.user.is_staff is False


def test_update_profile_rejects_unknown_timezone(client_for, admin):
    response = client_for(admin).patch(reverse("me"), {"timezone": "Mars/Olympus"}, format="json")
    assert response.status_code == 400
    assert "timezone" in response.json()["error"]["details"]


# ---------------------------------------------------------------- change password
def test_change_password_requires_current_password(client_for, admin):
    response = client_for(admin).post(
        reverse("me-password"), {"current_password": "nope", "new_password": "Another-Strong-99"}, format="json"
    )
    assert response.status_code == 400
    assert "current_password" in response.json()["error"]["details"]


def test_change_password_revokes_other_sessions_and_issues_new_one(api_client, client_for, admin):
    login(api_client, admin.user.email)
    other_session = api_client.cookies[COOKIE].value

    client = client_for(admin)
    response = client.post(
        reverse("me-password"), {"current_password": PASSWORD, "new_password": "Another-Strong-99"}, format="json"
    )
    assert response.status_code == 200
    assert response.cookies[COOKIE].value

    api_client.cookies[COOKIE] = other_session
    assert api_client.post(reverse("auth-refresh")).status_code == 401
    assert login(api_client, admin.user.email, "Another-Strong-99").status_code == 200


def test_change_password_enforces_validators(client_for, admin):
    response = client_for(admin).post(
        reverse("me-password"), {"current_password": PASSWORD, "new_password": "123"}, format="json"
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    admin.user.refresh_from_db()
    assert admin.user.check_password(PASSWORD)  # unchanged


# ----------------------------------------------------------- forgot/reset password
def _reset_params(body: str) -> tuple[str, str]:
    match = re.search(r"reset-password\?uid=([^&\s]+)&token=([^\s]+)", body)
    assert match, body
    return match.group(1), match.group(2)


def test_forgot_password_unknown_email_does_not_reveal_anything(api_client, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.post(reverse("auth-password-forgot"), {"email": "ghost@x.test"}, format="json")
    assert response.status_code == 202
    assert len(mail.outbox) == 0


def test_password_reset_full_flow_is_single_use(api_client, admin, django_capture_on_commit_callbacks):
    login(api_client, admin.user.email)
    old_session = api_client.cookies[COOKIE].value

    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.post(reverse("auth-password-forgot"), {"email": admin.user.email}, format="json")
    assert response.status_code == 202
    assert len(mail.outbox) == 1
    uid, token = _reset_params(mail.outbox[0].body)

    payload = {"uid": uid, "token": token, "new_password": "Brand-New-Pass-7"}
    assert api_client.post(reverse("auth-password-reset"), payload, format="json").status_code == 200
    reuse_payload = {**payload, "new_password": "Other-Pass-88x"}
    reuse = api_client.post(reverse("auth-password-reset"), reuse_payload, format="json")
    assert reuse.status_code == 400

    assert login(api_client, admin.user.email, "Brand-New-Pass-7").status_code == 200
    api_client.cookies[COOKIE] = old_session
    assert api_client.post(reverse("auth-refresh")).status_code == 401  # all prior sessions revoked


def test_password_reset_rejects_tampered_token(api_client, admin):
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode

    uid = urlsafe_base64_encode(force_bytes(admin.user.pk))
    response = api_client.post(
        reverse("auth-password-reset"), {"uid": uid, "token": "bogus-token", "new_password": "Brand-New-Pass-7"},
        format="json",
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------- register
def test_registration_disabled_by_default(api_client):
    response = api_client.post(reverse("auth-register"), {}, format="json")
    assert response.status_code == 404


def test_registration_creates_org_and_admin_when_enabled(api_client, settings):
    settings.REGISTRATION_ENABLED = True
    payload = {
        "organization_name": "New Co", "first_name": "Nia", "last_name": "New",
        "email": "nia@newco.test", "password": "Sufficiently-Long-1",
    }
    response = api_client.post(reverse("auth-register"), payload, format="json")
    assert response.status_code == 201
    assert response.json()["user"]["role"]["code"] == "org_admin"
    assert response.json()["user"]["organization"]["slug"] == "new-co"
    assert api_client.post(reverse("auth-register"), payload, format="json").status_code == 409
