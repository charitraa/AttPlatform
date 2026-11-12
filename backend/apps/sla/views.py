from datetime import timedelta

from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.core.exceptions import Conflict
from apps.organizations.permissions import HasPermission, MethodPermissions
from apps.tickets.selectors import visible_tickets

from . import services
from .models import BusinessHours, SLAInstance, SLAPolicy
from .serializers import BusinessHoursSerializer, SLAInstanceSerializer, SLAPolicySerializer

SLA_PERMS = {
    "GET": ["sla.view"],
    "POST": ["sla.manage"],
    "PUT": ["sla.manage"],
    "PATCH": ["sla.manage"],
    "DELETE": ["sla.manage"],
}


class _AuditedViewSet(viewsets.ModelViewSet):
    permission_classes = [MethodPermissions]
    method_permissions = SLA_PERMS
    pagination_class = None
    audit_prefix = ""

    def perform_create(self, serializer):
        obj = serializer.save()
        audit.record(f"{self.audit_prefix}.created", request=self.request, target=obj, changes={"name": obj.name})

    def perform_update(self, serializer):
        obj = serializer.save()
        changed = sorted(k for k in serializer.validated_data)
        audit.record(f"{self.audit_prefix}.updated", request=self.request, target=obj, changes={"fields": changed})


@extend_schema(tags=["sla"])
class BusinessHoursViewSet(_AuditedViewSet):
    serializer_class = BusinessHoursSerializer
    audit_prefix = "business_hours"

    def get_queryset(self):
        return BusinessHours.objects.filter(organization=self.request.organization).prefetch_related(
            "holidays", "policies"
        )

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError as exc:
            raise Conflict("Policies still use these working hours. Point them elsewhere first.") from exc
        audit.record("business_hours.deleted", request=self.request, target_type="sla.businesshours",
                     target_id=str(instance.pk), changes={"name": instance.name})


@extend_schema(tags=["sla"])
class SLAPolicyViewSet(_AuditedViewSet):
    serializer_class = SLAPolicySerializer
    audit_prefix = "sla_policy"

    def get_queryset(self):
        return (
            SLAPolicy.objects.filter(organization=self.request.organization)
            .select_related("business_hours")
            .prefetch_related("targets")
        )

    def perform_destroy(self, instance):
        if instance.is_default:
            raise Conflict("The default policy can't be deleted. Make another policy the default first.")
        pk, name = instance.pk, instance.name
        instance.delete()  # running SLA clocks keep their snapshot (policy is SET_NULL)
        audit.record("sla_policy.deleted", request=self.request, target_type="sla.slapolicy",
                     target_id=str(pk), changes={"name": name})


@extend_schema(tags=["sla"], responses=SLAInstanceSerializer)
class TicketSLAView(APIView):
    """The SLA clock and its events for one ticket (`null` when no policy applies)."""

    permission_classes = [HasPermission("sla.view")]

    def get(self, request, ticket_id):
        ticket = get_object_or_404(visible_tickets(request.tenant), pk=ticket_id)
        sla = (
            SLAInstance.objects.filter(ticket=ticket)
            .select_related("business_hours")
            .prefetch_related("business_hours__holidays", "events__actor")
            .first()
        )
        return Response(SLAInstanceSerializer(sla).data if sla else None)


@extend_schema(
    tags=["sla"],
    parameters=[
        OpenApiParameter("start", OpenApiTypes.DATETIME, description="Default: 30 days ago."),
        OpenApiParameter("end", OpenApiTypes.DATETIME, description="Default: now. At most 366 days after start."),
    ],
    responses=OpenApiTypes.OBJECT,
)
class SLAReportView(APIView):
    """Met vs breached per priority for tickets opened in the period."""

    permission_classes = [HasPermission("sla.view")]

    def get(self, request):
        def when(name, default):
            raw = request.query_params.get(name)
            if not raw:
                return default
            value = parse_datetime(raw)
            if value is not None and timezone.is_naive(value):
                value = timezone.make_aware(value, timezone.get_current_timezone())
            return value

        end = when("end", timezone.now())
        start = when("start", end - timedelta(days=30) if end else None)
        if start is None or end is None or end <= start:
            raise exceptions.ValidationError({"start": ["Provide ISO start and end datetimes (end after start)."]})
        if end - start > timedelta(days=366):
            raise exceptions.ValidationError({"end": ["The range may be at most 366 days."]})
        return Response(services.compliance(request.organization, start=start, end=end))
