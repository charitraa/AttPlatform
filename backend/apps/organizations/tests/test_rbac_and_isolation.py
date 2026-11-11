import pytest
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.organizations.catalog import PERMISSIONS, SYSTEM_ROLES, RoleCode
from apps.organizations.models import Role
from apps.organizations.services import sync_roles_and_permissions

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------- catalog
def test_system_roles_are_synced_from_catalog():
    assert set(Role.objects.filter(organization=None).values_list("code", flat=True)) == set(SYSTEM_ROLES)
    agent = Role.objects.get(code=RoleCode.SUPPORT_AGENT)
    assert set(agent.permissions.values_list("code", flat=True)) == SYSTEM_ROLES[RoleCode.SUPPORT_AGENT].permissions


def test_sync_is_idempotent_and_repairs_drift():
    agent = Role.objects.get(code=RoleCode.SUPPORT_AGENT)
    agent.permissions.clear()
    sync_roles_and_permissions()
    sync_roles_and_permissions()
    assert agent.permissions.count() == len(SYSTEM_ROLES[RoleCode.SUPPORT_AGENT].permissions)


def test_super_admin_has_every_permission(client_for, org, make_member):
    body = client_for(make_member(org, RoleCode.SUPER_ADMIN)).get(reverse("me")).json()
    assert set(body["permissions"]) == set(PERMISSIONS)


# ------------------------------------------------------------- role enforcement
@pytest.mark.parametrize(
    "role,method,url_name,expected",
    [
        (RoleCode.SUPPORT_AGENT, "get", "invitation-list", 403),
        (RoleCode.FIELD_TECHNICIAN, "get", "member-list", 403),
        (RoleCode.CUSTOMER, "get", "member-list", 403),
        (RoleCode.CUSTOMER, "get", "organization", 200),
        (RoleCode.CUSTOMER, "patch", "organization", 403),
        (RoleCode.OPS_MANAGER, "patch", "organization", 403),
        (RoleCode.OPS_MANAGER, "get", "member-list", 200),
        (RoleCode.OPS_MANAGER, "get", "audit-log-list", 200),
        (RoleCode.SUPPORT_AGENT, "get", "audit-log-list", 403),
        (RoleCode.ORG_ADMIN, "get", "invitation-list", 200),
    ],
)
def test_endpoint_access_by_role(client_for, org, make_member, role, method, url_name, expected):
    client = client_for(make_member(org, role))
    response = getattr(client, method)(reverse(url_name), {}, format="json")
    assert response.status_code == expected
    if expected == 403:
        assert response.json()["error"]["code"] == "permission_denied"


def test_user_without_membership_gets_no_organization_error(client_for, org, make_member):
    member = make_member(org, is_active=False)
    response = client_for(member).get(reverse("me"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "no_organization"


# --------------------------------------------------------- organization settings
def test_admin_updates_organization_and_change_is_audited(client_for, admin):
    response = client_for(admin).patch(
        reverse("organization"),
        {"name": "Acme Ltd", "timezone": "Asia/Kathmandu", "settings": {"routing_policy": "auto"}},
        format="json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Acme Ltd"
    assert body["settings"]["routing_policy"] == "auto"
    assert body["settings"]["ai_enabled"] is True  # defaults are filled in
    assert AuditLog.objects.filter(action="organization.updated", organization=admin.organization).exists()


def test_organization_rejects_unknown_settings_and_ignores_slug(client_for, admin):
    client = client_for(admin)
    bad = client.patch(reverse("organization"), {"settings": {"evil": 1}}, format="json")
    assert bad.status_code == 400
    client.patch(reverse("organization"), {"slug": "hijack"}, format="json")
    admin.organization.refresh_from_db()
    assert admin.organization.slug != "hijack"


# ---------------------------------------------------------------- isolation
def test_member_list_is_scoped_to_own_organization(client_for, admin, other_org, make_member):
    make_member(admin.organization)
    outsider = make_member(other_org)
    ids = {m["id"] for m in client_for(admin).get(reverse("member-list")).json()["results"]}
    assert str(outsider.user.id) not in ids
    assert str(admin.user.id) in ids


def test_other_organization_user_is_not_found_for_read_or_write(client_for, admin, other_org, make_member):
    outsider = make_member(other_org)
    client = client_for(admin)
    url = reverse("member-detail", args=[outsider.user.id])
    assert client.get(url).status_code == 404
    assert client.patch(url, {"role": "customer"}, format="json").status_code == 404
    assert client.delete(url).status_code == 404
    outsider.refresh_from_db()
    assert outsider.role.code == RoleCode.SUPPORT_AGENT and outsider.is_active


def test_org_header_for_non_member_org_is_refused(client_for, admin, other_org):
    response = client_for(admin, org_slug=other_org.slug).get(reverse("organization"))
    assert response.status_code == 403


def test_org_header_selects_among_users_memberships(client_for, admin, other_org, make_member):
    make_member(other_org, RoleCode.SUPPORT_AGENT, email=admin.user.email)
    body = client_for(admin, org_slug=other_org.slug).get(reverse("me")).json()
    assert body["organization"]["slug"] == other_org.slug
    assert body["role"]["code"] == RoleCode.SUPPORT_AGENT
    assert len(body["memberships"]) == 2


def test_audit_log_is_scoped_to_own_organization(client_for, admin, other_org, make_member):
    other_admin = make_member(other_org, RoleCode.ORG_ADMIN)
    client_for(other_admin).patch(reverse("organization"), {"name": "Globex 2"}, format="json")
    actions = client_for(admin).get(reverse("audit-log-list")).json()["results"]
    assert all(a["actor"] is None or a["actor"]["email"] != other_admin.user.email for a in actions)


def test_audit_log_is_append_only(admin):
    entry = AuditLog.objects.create(action="test.event", organization=admin.organization)
    entry.action = "tampered"
    with pytest.raises(RuntimeError):
        entry.save()


# --------------------------------------------------- privilege escalation guards
def test_admin_changes_member_role(client_for, admin, make_member):
    agent = make_member(admin.organization)
    response = client_for(admin).patch(reverse("member-detail", args=[agent.user.id]), {"role": "ops_manager"},
                                       format="json")
    assert response.status_code == 200
    assert response.json()["role"]["code"] == "ops_manager"
    log = AuditLog.objects.get(action="membership.role_changed")
    assert log.changes["role"] == {"from": "support_agent", "to": "ops_manager"}


def test_org_admin_cannot_grant_super_admin(client_for, admin, make_member):
    agent = make_member(admin.organization)
    response = client_for(admin).patch(reverse("member-detail", args=[agent.user.id]), {"role": "super_admin"},
                                       format="json")
    assert response.status_code == 403


def test_ops_manager_cannot_grant_higher_role_or_manage_admins(client_for, admin, make_member):
    ops = make_member(admin.organization, RoleCode.OPS_MANAGER)
    agent = make_member(admin.organization)
    # ops managers can view users but lack users.manage entirely
    client = client_for(ops)
    assert client.patch(reverse("member-detail", args=[agent.user.id]), {"role": "org_admin"},
                        format="json").status_code == 403
    assert client.patch(reverse("member-detail", args=[admin.user.id]), {"is_active": False},
                        format="json").status_code == 403


def test_cannot_change_own_role(client_for, admin):
    response = client_for(admin).patch(reverse("member-detail", args=[admin.user.id]), {"role": "customer"},
                                       format="json")
    assert response.status_code == 400


def test_org_admin_cannot_modify_super_admin(client_for, admin, make_member):
    root = make_member(admin.organization, RoleCode.SUPER_ADMIN)
    response = client_for(admin).patch(reverse("member-detail", args=[root.user.id]), {"is_active": False},
                                       format="json")
    assert response.status_code == 403


def test_admin_can_deactivate_a_co_admin(client_for, admin, make_member):
    co_admin = make_member(admin.organization, RoleCode.ORG_ADMIN)
    response = client_for(admin).patch(reverse("member-detail", args=[co_admin.user.id]), {"is_active": False},
                                       format="json")
    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_last_admin_guard(admin, make_member):
    """
    Through the API the actor is always an admin (and counted), so this guard is
    defence in depth for custom roles / scripts; exercise it at the service level.
    """
    from apps.core.exceptions import DomainError
    from apps.organizations.services import _ensure_admin_remains

    with pytest.raises(DomainError):
        _ensure_admin_remains(admin.organization, excluding=admin)
    make_member(admin.organization, RoleCode.SUPER_ADMIN)
    _ensure_admin_remains(admin.organization, excluding=admin)  # another admin exists: no error


def test_deactivating_member_revokes_their_session(api_client, client_for, admin, make_member):
    from django.conf import settings

    agent = make_member(admin.organization)
    api_client.post(reverse("auth-login"), {"email": agent.user.email, "password": "Correct-Horse-42!"}, format="json")
    assert client_for(admin).delete(reverse("member-detail", args=[agent.user.id])).status_code == 204
    agent.refresh_from_db()
    assert agent.is_active is False
    assert settings.REFRESH_COOKIE_NAME in api_client.cookies  # client still holds the (now revoked) cookie
    assert api_client.post(reverse("auth-refresh")).status_code == 401


def test_roles_endpoint_marks_assignable_roles(client_for, admin):
    roles = {r["code"]: r for r in client_for(admin).get(reverse("role-list")).json()}
    assert roles["org_admin"]["assignable"] is True
    assert roles["super_admin"]["assignable"] is False
    assert "users.manage" in roles["org_admin"]["permissions"]
