"""
Permission catalog and system role definitions — the single source of truth for RBAC.

The database tables (`Permission`, `Role`, `RolePermission`) mirror this module and
are synchronised on every `migrate` (see `services.sync_roles_and_permissions`).
Code checks permissions by code string, e.g. `HasPermission("users.manage")`.

Permissions for modules delivered in later phases are declared now so role
definitions stay stable as features land.
"""
from dataclasses import dataclass


class RoleCode:
    SUPER_ADMIN = "super_admin"
    ORG_ADMIN = "org_admin"
    OPS_MANAGER = "ops_manager"
    SUPPORT_AGENT = "support_agent"
    FIELD_TECHNICIAN = "field_technician"
    CUSTOMER = "customer"


PERMISSIONS: dict[str, str] = {
    # Organization & identity (Phase 2)
    "organization.view": "View organization profile",
    "organization.manage": "Edit organization profile and settings",
    "users.view": "View users in the organization",
    "users.manage": "Change user roles and deactivate users",
    "invitations.manage": "Invite users and revoke invitations",
    "roles.view": "View roles and their permissions",
    "audit.view": "View the audit log",
    # Ticketing (Phase 3)
    "tickets.view_all": "View all tickets in the organization",
    "tickets.view_own": "View own / assigned tickets only",
    "tickets.create": "Create tickets",
    "tickets.update": "Edit tickets and change status",
    "tickets.assign": "Assign tickets to agents and technicians",
    "tickets.archive": "Archive tickets",
    "tickets.internal_notes": "Read and write internal notes",
    "customers.view": "View customers",
    "customers.manage": "Create and edit customers",
    "assets.view": "View assets",
    "assets.manage": "Create and edit assets",
    # AI (Phase 4)
    "ai.use": "Run AI analysis and use the AI assistant",
    "ai.override": "Accept, reject or override AI recommendations",
    "knowledge.view": "Read the knowledge base",
    "knowledge.manage": "Create, review and publish knowledge articles",
    # Field service (Phase 5)
    "technicians.view": "View technicians",
    "technicians.manage": "Manage technicians, skills and availability",
    "work_orders.view_all": "View all work orders",
    "work_orders.view_own": "View own assigned work orders only",
    "work_orders.manage": "Create, assign and cancel work orders",
    "work_orders.execute": "Update status and upload evidence on own work orders",
    "schedule.view": "View the scheduling calendar",
    "location.view": "View technician locations",
    # SLA & notifications (Phase 6)
    "sla.view": "View SLA policies and status",
    "sla.manage": "Manage SLA policies and business hours",
    # Integrations, analytics, portal (Phase 7)
    "integrations.manage": "Configure integrations and credentials",
    "analytics.view": "View analytics and export reports",
    "portal.access": "Use the customer portal",
    "feedback.submit": "Submit customer feedback",
}


@dataclass(frozen=True)
class RoleDefinition:
    code: str
    name: str
    description: str
    rank: int  # privilege level; an actor may only grant roles at or below their own rank
    permissions: frozenset[str]


def _perms(*codes: str) -> frozenset[str]:
    unknown = set(codes) - PERMISSIONS.keys()
    if unknown:
        raise ValueError(f"Unknown permission codes: {sorted(unknown)}")
    return frozenset(codes)


_STAFF_COMMON = (
    "organization.view", "roles.view", "knowledge.view", "customers.view", "assets.view",
    "technicians.view", "schedule.view", "sla.view",
)

SYSTEM_ROLES: dict[str, RoleDefinition] = {
    r.code: r
    for r in (
        RoleDefinition(
            RoleCode.SUPER_ADMIN, "Super Admin", "Platform operator with every permission.", 100,
            frozenset(PERMISSIONS),
        ),
        RoleDefinition(
            RoleCode.ORG_ADMIN, "Organization Admin", "Manages the organization, its users and configuration.", 80,
            frozenset(PERMISSIONS) - {"portal.access", "feedback.submit", "work_orders.view_own", "tickets.view_own",
                                      "work_orders.execute"},
        ),
        RoleDefinition(
            RoleCode.OPS_MANAGER, "Operations Manager", "Runs service operations, dispatch and SLAs.", 60,
            _perms(
                *_STAFF_COMMON, "users.view", "audit.view",
                "tickets.view_all", "tickets.create", "tickets.update", "tickets.assign", "tickets.archive",
                "tickets.internal_notes", "customers.manage", "assets.manage",
                "ai.use", "ai.override", "knowledge.manage",
                "technicians.manage", "work_orders.view_all", "work_orders.manage", "location.view",
                "sla.manage", "analytics.view",
            ),
        ),
        RoleDefinition(
            RoleCode.SUPPORT_AGENT, "Support Agent", "Handles tickets and customer communication.", 40,
            _perms(
                *_STAFF_COMMON, "users.view",
                "tickets.view_all", "tickets.create", "tickets.update", "tickets.internal_notes",
                "customers.manage", "ai.use", "work_orders.view_all",
            ),
        ),
        RoleDefinition(
            RoleCode.FIELD_TECHNICIAN, "Field Technician", "Performs on-site work orders.", 30,
            _perms(
                "organization.view", "knowledge.view", "customers.view", "assets.view", "schedule.view",
                "tickets.view_own", "tickets.internal_notes", "ai.use",
                "work_orders.view_own", "work_orders.execute",
            ),
        ),
        RoleDefinition(
            RoleCode.CUSTOMER, "Customer", "Customer contact using the self-service portal.", 10,
            _perms("organization.view", "portal.access", "tickets.view_own", "tickets.create", "feedback.submit"),
        ),
    )
}

STAFF_ROLES = frozenset(SYSTEM_ROLES) - {RoleCode.CUSTOMER}


def role_rank(code: str) -> int:
    return SYSTEM_ROLES[code].rank if code in SYSTEM_ROLES else 0
