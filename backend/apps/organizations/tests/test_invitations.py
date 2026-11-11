import re
from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.organizations.catalog import RoleCode
from apps.organizations.models import Invitation, Membership
from conftest import PASSWORD

pytestmark = pytest.mark.django_db


@pytest.fixture
def invite(client_for, admin, django_capture_on_commit_callbacks):
    """Create an invitation through the API and return (response, raw token from the email)."""

    def _invite(email="new.hire@acme.test", role="support_agent", actor=None):
        with django_capture_on_commit_callbacks(execute=True):
            response = client_for(actor or admin).post(reverse("invitation-list"), {"email": email, "role": role},
                                                       format="json")
        token = None
        if response.status_code == 201:
            match = re.search(r"accept-invite\?token=(\S+)", mail.outbox[-1].body)
            token = match.group(1)
        return response, token

    return _invite


def accept(client, token, password="Fresh-Hire-Pass-1", **extra):
    return client.post(reverse("auth-invitation-accept"),
                       {"token": token, "password": password, "first_name": "New", "last_name": "Hire", **extra},
                       format="json")


def test_invitation_is_emailed_and_token_stored_hashed(invite):
    response, token = invite()
    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert mail.outbox[-1].to == ["new.hire@acme.test"]
    invitation = Invitation.objects.get()
    assert token not in invitation.token_hash  # only the hash is persisted
    assert len(invitation.token_hash) == 64


def test_preview_then_accept_creates_user_membership_and_session(api_client, invite, admin):
    _, token = invite()
    preview = api_client.post(reverse("auth-invitation-preview"), {"token": token}, format="json").json()
    assert preview == {"organization_name": "Acme", "email": "new.hire@acme.test", "role_name": "Support Agent",
                       "existing_account": False}

    response = accept(api_client, token)
    assert response.status_code == 201
    assert response.json()["user"]["role"]["code"] == "support_agent"
    assert response.json()["access"]
    membership = Membership.objects.get(user__email="new.hire@acme.test")
    assert membership.organization == admin.organization
    assert membership.invited_by == admin.user


def test_invitation_token_is_single_use(api_client, invite):
    _, token = invite()
    assert accept(api_client, token).status_code == 201
    assert accept(api_client, token).status_code == 400


def test_expired_and_revoked_invitations_cannot_be_used(api_client, client_for, admin, invite):
    _, token = invite()
    Invitation.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    assert accept(api_client, token).status_code == 400

    _, token2 = invite(email="second@acme.test")
    invitation = Invitation.objects.get(email="second@acme.test")
    assert client_for(admin).delete(reverse("invitation-detail", args=[invitation.id])).status_code == 204
    assert accept(api_client, token2).status_code == 400


def test_resend_rotates_token(api_client, client_for, admin, invite, django_capture_on_commit_callbacks):
    _, old_token = invite()
    invitation = Invitation.objects.get()
    with django_capture_on_commit_callbacks(execute=True):
        client_for(admin).post(reverse("invitation-resend", args=[invitation.id]))
    new_token = re.search(r"accept-invite\?token=(\S+)", mail.outbox[-1].body).group(1)
    assert new_token != old_token
    assert accept(api_client, old_token).status_code == 400
    assert accept(api_client, new_token).status_code == 201


def test_duplicate_open_invitation_and_existing_member_conflict(invite, admin):
    assert invite()[0].status_code == 201
    assert invite()[0].status_code == 409
    assert invite(email=admin.user.email)[0].status_code == 409


def test_existing_user_must_prove_password_to_join(api_client, invite, other_org, make_member):
    existing = make_member(other_org, email="known@person.test")
    _, token = invite(email="known@person.test")
    preview = api_client.post(reverse("auth-invitation-preview"), {"token": token}, format="json").json()
    assert preview["existing_account"] is True
    assert accept(api_client, token, password="not-their-password").status_code == 400
    assert accept(api_client, token, password=PASSWORD).status_code == 201
    assert existing.user.memberships.count() == 2


def test_agents_cannot_invite(invite, admin, make_member):
    agent = make_member(admin.organization, RoleCode.SUPPORT_AGENT)
    assert invite(actor=agent)[0].status_code == 403


def test_admin_cannot_invite_super_admin(invite):
    assert invite(role="super_admin")[0].status_code == 403


def test_invitations_list_is_scoped_and_filterable(client_for, admin, other_org, make_member, invite):
    invite()
    other_admin = make_member(other_org, RoleCode.ORG_ADMIN)
    assert client_for(other_admin).get(reverse("invitation-list")).json()["count"] == 0
    assert client_for(admin).get(reverse("invitation-list"), {"status": "pending"}).json()["count"] == 1
    assert client_for(admin).get(reverse("invitation-list"), {"status": "accepted"}).json()["count"] == 0


def test_weak_password_rejected_on_accept(api_client, invite):
    _, token = invite()
    response = accept(api_client, token, password="short")
    assert response.status_code == 400
    assert not Membership.objects.filter(user__email="new.hire@acme.test").exists()
