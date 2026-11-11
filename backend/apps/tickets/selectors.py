"""Read-side queries. Every ticket query starts from `visible_tickets` so row-level rules apply everywhere."""

from django.db.models import Case, IntegerField, Q, QuerySet, Value, When

from apps.customers.models import CustomerContact
from apps.organizations.tenancy import TenantContext

from .models import PRIORITY_RANK, Ticket, TicketComment, TicketHistory


def is_staff_actor(tenant: TenantContext) -> bool:
    """Staff = anyone who works tickets (not a customer-portal user)."""
    return "portal.access" not in tenant.permissions or "tickets.view_all" in tenant.permissions


def can_see_internal(tenant: TenantContext) -> bool:
    return "tickets.internal_notes" in tenant.permissions


def customer_ids_for_user(user, organization) -> QuerySet:
    return CustomerContact.objects.filter(user=user, customer__organization=organization).values("customer_id")


def visible_tickets(tenant: TenantContext) -> QuerySet[Ticket]:
    user, org, perms = tenant.membership.user, tenant.organization, tenant.permissions
    qs = Ticket.objects.filter(organization=org)
    if "tickets.view_all" in perms:
        return qs
    if "tickets.view_own" not in perms:
        return qs.none()
    if "portal.access" in perms:
        # Customer users see their customer accounts' tickets (and any they raised).
        return qs.filter(Q(customer_id__in=customer_ids_for_user(user, org)) | Q(created_by=user))
    # Technicians (and other "own" roles): assigned to them or raised by them.
    return qs.filter(Q(assigned_technician=user) | Q(assigned_agent=user) | Q(created_by=user))


def with_detail_relations(qs: QuerySet[Ticket]) -> QuerySet[Ticket]:
    return qs.select_related(
        "customer",
        "contact",
        "asset",
        "category",
        "category__parent",
        "assigned_agent",
        "assigned_technician",
        "created_by",
    )


def priority_rank_expression():
    return Case(*[When(priority=p, then=Value(r)) for p, r in PRIORITY_RANK.items()], output_field=IntegerField())


def visible_comments(ticket: Ticket, tenant: TenantContext) -> QuerySet[TicketComment]:
    qs = ticket.comments.select_related("author").prefetch_related("attachments")
    return qs if can_see_internal(tenant) else qs.filter(visibility=TicketComment.Visibility.PUBLIC)


def visible_attachments(ticket: Ticket, tenant: TenantContext):
    qs = ticket.attachments.select_related("uploaded_by")
    return qs if can_see_internal(tenant) else qs.filter(visibility=TicketComment.Visibility.PUBLIC)


def visible_history(ticket: Ticket, tenant: TenantContext) -> QuerySet[TicketHistory]:
    qs = ticket.history.select_related("actor")
    return qs if can_see_internal(tenant) else qs.filter(internal=False)
