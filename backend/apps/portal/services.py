from django.db import IntegrityError, transaction
from rest_framework import exceptions

from apps.audit import services as audit
from apps.core.exceptions import Conflict
from apps.field_service.models import WorkOrder, WorkOrderStatus
from apps.organizations.tenancy import TenantContext
from apps.tickets.models import TicketStatus
from apps.tickets.selectors import customer_ids_for_user, visible_tickets

from .models import CustomerFeedback


@transaction.atomic
def submit_feedback(*, tenant: TenantContext, data: dict, request=None) -> CustomerFeedback:
    user, org = tenant.membership.user, tenant.organization
    if data.get("ticket"):
        ticket = visible_tickets(tenant).filter(pk=data["ticket"]).first()
        if ticket is None:
            raise exceptions.NotFound("Ticket not found.")
        if ticket.status not in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
            raise exceptions.ValidationError({"ticket": ["You can rate a ticket once it has been resolved."]})
        subject = {"ticket": ticket, "customer_id": ticket.customer_id}
    else:
        wo = WorkOrder.objects.filter(
            organization=org, pk=data["work_order"], customer_id__in=customer_ids_for_user(user, org)
        ).first()
        if wo is None:
            raise exceptions.NotFound("Work order not found.")
        if wo.status != WorkOrderStatus.COMPLETED:
            raise exceptions.ValidationError({"work_order": ["You can rate a visit once it's completed."]})
        subject = {"work_order": wo, "customer_id": wo.customer_id}
    try:
        with transaction.atomic():
            fb = CustomerFeedback.objects.create(
                organization=org,
                submitted_by=user,
                rating=data["rating"],
                comment=data.get("comment", "").strip(),
                **subject,
            )
    except IntegrityError as exc:
        raise Conflict("You've already rated this.") from exc
    audit.record("feedback.submitted", request=request, target=fb, changes={"rating": fb.rating})
    return fb
