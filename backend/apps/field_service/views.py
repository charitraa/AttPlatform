import re
from datetime import timedelta

from django.db.models import Count, Prefetch, Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.permissions import HasPermission, MethodPermissions

from . import selectors, services
from .models import (
    ACTIVE_WORK_ORDER_STATUSES,
    Appointment,
    ServiceArea,
    Skill,
    Technician,
    TechnicianAvailability,
    TechnicianCertification,
    TechnicianLocation,
    TechnicianSkill,
    WorkOrder,
)
from .serializers import (
    AdvanceSerializer,
    AppointmentSerializer,
    AssignSerializer,
    AvailabilitySerializer,
    CertificationSerializer,
    ConfirmSerializer,
    EvidenceSerializer,
    EvidenceUploadSerializer,
    LocationSerializer,
    MyProfileSerializer,
    ReasonSerializer,
    ScheduleSerializer,
    ServiceAreaSerializer,
    SkillSerializer,
    StatusLogSerializer,
    TechnicianSerializer,
    TechnicianSkillSerializer,
    WorkOrderCreateSerializer,
    WorkOrderDetailSerializer,
    WorkOrderListSerializer,
    WorkOrderUpdateSerializer,
)

TECH_READ = ["technicians.view"]
TECH_PERMS = {
    "GET": TECH_READ,
    "POST": ["technicians.manage"],
    "PATCH": ["technicians.manage"],
    "PUT": ["technicians.manage"],
    "DELETE": ["technicians.manage"],
}
WO_VIEW = ["work_orders.view_all", "work_orders.view_own"]


def score_dict(s) -> dict:
    return {
        "technician_id": s.technician_id,
        "user_id": s.user_id,
        "name": s.name,
        "status": s.status,
        "score": s.score,
        "factors": s.factors,
        "active_jobs": s.active_jobs,
        "distance_km": s.distance_km,
        "matched_skills": s.matched_skills,
        "missing_skills": s.missing_skills,
        "blocked_reason": s.blocked_reason,
    }


# ----------------------------------------------------------------- reference data
@extend_schema(tags=["field service"])
class SkillViewSet(viewsets.ModelViewSet):
    permission_classes = [MethodPermissions]
    method_permissions = TECH_PERMS
    serializer_class = SkillSerializer
    pagination_class = None

    def get_queryset(self):
        return Skill.objects.filter(organization=self.request.organization).prefetch_related("ticket_categories")

    def perform_create(self, serializer):
        serializer.save(organization=self.request.organization)


@extend_schema(tags=["field service"])
class ServiceAreaViewSet(viewsets.ModelViewSet):
    permission_classes = [MethodPermissions]
    method_permissions = TECH_PERMS
    serializer_class = ServiceAreaSerializer
    pagination_class = None

    def get_queryset(self):
        return ServiceArea.objects.filter(organization=self.request.organization)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.organization)


# -------------------------------------------------------------------- technicians
@extend_schema(tags=["field service"])
class TechnicianViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    """
    Technician profiles exist for every active Field Technician (created automatically).
    Technicians may manage their own availability; everything else needs technicians.manage.
    """

    permission_classes = [MethodPermissions]
    method_permissions = TECH_PERMS
    serializer_class = TechnicianSerializer
    search_fields = ("user__first_name", "user__last_name", "user__email", "employee_id", "skills__skill__name")
    filterset_fields = ("status",)

    def get_permissions(self):
        if self.action in ("me", "my_location"):
            return [HasPermission("work_orders.execute")()]
        if self.action in ("availability", "remove_availability"):
            return [HasPermission("technicians.view", "work_orders.execute", any_of=True)()]
        return super().get_permissions()

    def get_queryset(self):
        today = timezone.localdate()
        return (
            selectors.active_technicians(self.request.organization)
            .prefetch_related(
                Prefetch("skills", queryset=TechnicianSkill.objects.select_related("skill")), "service_areas"
            )
            .annotate(
                active_jobs=Count(
                    "work_orders", filter=Q(work_orders__status__in=ACTIVE_WORK_ORDER_STATUSES), distinct=True
                ),
                jobs_today=Count(
                    "appointments",
                    filter=Q(appointments__status=Appointment.Status.CONFIRMED, appointments__starts_at__date=today),
                    distinct=True,
                ),
            )
            .order_by("user__first_name", "user__last_name", "id")  # stable pagination
        )

    def perform_update(self, serializer):
        from apps.audit import services as audit

        tech = serializer.save()
        audit.record(
            "technician.updated",
            request=self.request,
            target=tech,
            changes={k: str(v) for k, v in serializer.validated_data.items()},
        )

    def _own_or_manager(self, tech: Technician) -> None:
        if "technicians.manage" not in self.request.tenant.permissions and tech.user_id != self.request.user.id:
            raise exceptions.PermissionDenied("You can only manage your own availability.")

    @extend_schema(request=TechnicianSkillSerializer(many=True), responses=TechnicianSkillSerializer(many=True))
    @action(detail=True, methods=["put"])
    def skills(self, request, pk=None):
        """Replace the technician's skills: [{skill, level}]."""
        tech = self.get_object()
        s = TechnicianSkillSerializer(data=request.data, many=True, context=self.get_serializer_context())
        s.is_valid(raise_exception=True)
        tech.skills.all().delete()
        TechnicianSkill.objects.bulk_create(
            [TechnicianSkill(technician=tech, skill=row["skill"], level=row["level"]) for row in s.validated_data]
        )
        return Response(TechnicianSkillSerializer(tech.skills.select_related("skill"), many=True).data)

    @extend_schema(methods=["GET"], responses=CertificationSerializer(many=True))
    @extend_schema(methods=["POST"], request=CertificationSerializer, responses={201: CertificationSerializer})
    @action(detail=True, methods=["get", "post"], pagination_class=None)
    def certifications(self, request, pk=None):
        tech = self.get_object()
        if request.method == "POST":
            s = CertificationSerializer(data=request.data)
            s.is_valid(raise_exception=True)
            return Response(CertificationSerializer(s.save(technician=tech)).data, status=status.HTTP_201_CREATED)
        return Response(CertificationSerializer(tech.certifications.all(), many=True).data)

    @extend_schema(request=None, responses={204: None})
    @action(detail=True, methods=["delete"], url_path=r"certifications/(?P<cert_id>[^/.]+)")
    def remove_certification(self, request, pk=None, cert_id=None):
        get_object_or_404(TechnicianCertification, technician=self.get_object(), pk=cert_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(methods=["GET"], responses=AvailabilitySerializer(many=True))
    @extend_schema(methods=["POST"], request=AvailabilitySerializer, responses={201: AvailabilitySerializer})
    @action(detail=True, methods=["get", "post"], pagination_class=None)
    def availability(self, request, pk=None):
        tech = self.get_object()
        if request.method == "POST":
            self._own_or_manager(tech)
            s = AvailabilitySerializer(data=request.data)
            s.is_valid(raise_exception=True)
            return Response(AvailabilitySerializer(s.save(technician=tech)).data, status=status.HTTP_201_CREATED)
        start = timezone.now() - timedelta(days=1)
        qs = tech.availability.filter(ends_at__gte=start).order_by("starts_at")[:100]
        return Response(AvailabilitySerializer(qs, many=True).data)

    @extend_schema(request=None, responses={204: None})
    @action(detail=True, methods=["delete"], url_path=r"availability/(?P<entry_id>[^/.]+)")
    def remove_availability(self, request, pk=None, entry_id=None):
        tech = self.get_object()
        self._own_or_manager(tech)
        get_object_or_404(TechnicianAvailability, technician=tech, pk=entry_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses=None)
    @action(detail=True, methods=["get"])
    def location(self, request, pk=None):
        """Latest location ping (dispatchers with location.view only)."""
        if "location.view" not in request.tenant.permissions:
            raise exceptions.PermissionDenied("You can't view technician locations.")
        loc = TechnicianLocation.objects.filter(technician=self.get_object()).first()
        if not loc:
            return Response({"location": None})
        return Response(
            {
                "location": {
                    "lat": str(loc.lat),
                    "lng": str(loc.lng),
                    "accuracy_m": loc.accuracy_m,
                    "recorded_at": loc.recorded_at,
                    "work_order_id": str(loc.work_order_id) if loc.work_order_id else None,
                }
            }
        )

    @extend_schema(methods=["GET"], responses=TechnicianSerializer)
    @extend_schema(methods=["PATCH"], request=MyProfileSerializer, responses=TechnicianSerializer)
    @action(detail=False, methods=["get", "patch"])
    def me(self, request):
        membership = request.membership
        tech = services.ensure_technician_profile(membership)
        if request.method == "PATCH":
            s = MyProfileSerializer(tech, data=request.data, partial=True)
            s.is_valid(raise_exception=True)
            s.save()
        return Response(
            TechnicianSerializer(self.get_queryset().get(pk=tech.pk), context=self.get_serializer_context()).data
        )

    @extend_schema(request=LocationSerializer, responses={201: None})
    @action(detail=False, methods=["post"], url_path="me/location")
    def my_location(self, request):
        s = LocationSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        services.record_location(tenant=request.tenant, **s.validated_data)
        return Response(status=status.HTTP_201_CREATED)


# -------------------------------------------------------------------- work orders
class WorkOrderFilter(filters.FilterSet):
    status = filters.CharFilter(method="filter_status", help_text="Comma-separated, or `active`.")
    technician = filters.CharFilter(method="filter_technician", help_text="Technician ID, `me` or `none`.")
    customer = filters.UUIDFilter(field_name="customer_id")
    ticket = filters.UUIDFilter(field_name="ticket_id")
    scheduled_after = filters.IsoDateTimeFilter(field_name="scheduled_start", lookup_expr="gte")
    scheduled_before = filters.IsoDateTimeFilter(field_name="scheduled_start", lookup_expr="lt")

    class Meta:
        model = WorkOrder
        fields = ()

    def filter_status(self, qs, name, value):
        values = {v.strip() for v in value.split(",") if v.strip()}
        if "active" in values:
            values = (values - {"active"}) | set(ACTIVE_WORK_ORDER_STATUSES) | {"created"}
        return qs.filter(status__in=values)

    def filter_technician(self, qs, name, value):
        if value == "none":
            return qs.filter(technician__isnull=True)
        if value == "me":
            return qs.filter(technician__user=self.request.user)
        return qs.filter(technician_id=value)


NUMBER_RE = re.compile(r"^(?:wo-?)?0*(\d{1,9})$", re.IGNORECASE)


@extend_schema(tags=["field service"])
class WorkOrderViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    filterset_class = WorkOrderFilter
    ordering_fields = ("created_at", "scheduled_start", "number", "updated_at")
    ordering = ("-created_at",)
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    action_permissions = {
        "list": WO_VIEW,
        "retrieve": WO_VIEW,
        "status_log": WO_VIEW,
        "evidence": WO_VIEW,
        "create": ["work_orders.manage"],
        "partial_update": ["work_orders.manage"],
        "assign": ["work_orders.manage"],
        "cancel": ["work_orders.manage"],
        "schedule": ["work_orders.manage"],
        "suggest_technicians": ["work_orders.manage"],
        "advance": ["work_orders.execute"],
        "decline": ["work_orders.execute"],
        "confirm": ["work_orders.manage", "work_orders.execute"],
    }

    def get_permissions(self):
        return [HasPermission(*self.action_permissions.get(self.action, WO_VIEW), any_of=True)()]

    def get_queryset(self):
        qs = (
            selectors.visible_work_orders(self.request.tenant)
            .select_related("customer", "technician__user", "ticket", "asset", "created_by")
            .prefetch_related("appointments")
        )
        term = self.request.query_params.get("search", "").strip()
        if term and self.action == "list":
            m = NUMBER_RE.match(term)
            qs = (
                qs.filter(number=int(m.group(1)))
                if m
                else qs.filter(
                    Q(title__icontains=term) | Q(customer__name__icontains=term) | Q(service_address__icontains=term)
                )
            )
        return qs

    def filter_queryset(self, queryset):
        return super().filter_queryset(queryset) if self.action == "list" else queryset

    def get_serializer_class(self):
        return WorkOrderListSerializer if self.action == "list" else WorkOrderDetailSerializer

    def _detail(self, wo, code=status.HTTP_200_OK, **extra):
        # After declining, a technician can no longer see the job; still return the state they just produced.
        fresh = self.get_queryset().filter(pk=wo.pk).first() or WorkOrder.objects.select_related(
            "customer", "technician__user", "ticket", "asset", "created_by"
        ).prefetch_related("appointments").get(pk=wo.pk)
        data = WorkOrderDetailSerializer(fresh, context=self.get_serializer_context()).data
        return Response({**data, **extra}, status=code)

    @extend_schema(request=WorkOrderCreateSerializer, responses={201: WorkOrderDetailSerializer})
    def create(self, request):
        s = WorkOrderCreateSerializer(data=request.data, context=self.get_serializer_context())
        s.is_valid(raise_exception=True)
        return self._detail(
            services.create_work_order(tenant=request.tenant, data=s.validated_data, request=request),
            status.HTTP_201_CREATED,
        )

    @extend_schema(request=WorkOrderUpdateSerializer, responses=WorkOrderDetailSerializer)
    def partial_update(self, request, pk=None):
        s = WorkOrderUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return self._detail(
            services.update_details(work_order=self.get_object(), data=s.validated_data, request=request)
        )

    @extend_schema(request=AssignSerializer, responses=WorkOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        s = AssignSerializer(data=request.data, context=self.get_serializer_context())
        s.is_valid(raise_exception=True)
        return self._detail(
            services.assign_technician(
                tenant=request.tenant,
                work_order=self.get_object(),
                technician=s.validated_data["technician"],
                request=request,
            )
        )

    @extend_schema(request=AdvanceSerializer, responses=WorkOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def advance(self, request, pk=None):
        s = AdvanceSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        completion = {
            k: d.pop(k) for k in ("completion_summary", "service_notes", "parts_used", "labor_minutes") if k in d
        }
        if "parts_used" in completion:
            completion["parts_used"] = [
                {**p, "unit_cost": str(p["unit_cost"]) if p.get("unit_cost") is not None else None}
                for p in completion["parts_used"]
            ]
        return self._detail(
            services.advance(
                tenant=request.tenant,
                work_order=self.get_object(),
                to_status=d["status"],
                note=d["note"],
                lat=d.get("lat"),
                lng=d.get("lng"),
                completion=completion,
                request=request,
            )
        )

    @extend_schema(request=ReasonSerializer, responses=WorkOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        s = ReasonSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return self._detail(
            services.decline(
                tenant=request.tenant, work_order=self.get_object(), reason=s.validated_data["reason"], request=request
            )
        )

    @extend_schema(request=ReasonSerializer, responses=WorkOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        s = ReasonSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return self._detail(
            services.cancel(
                tenant=request.tenant, work_order=self.get_object(), reason=s.validated_data["reason"], request=request
            )
        )

    @extend_schema(request=ConfirmSerializer, responses=WorkOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        s = ConfirmSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return self._detail(
            services.confirm(tenant=request.tenant, work_order=self.get_object(), request=request, **s.validated_data)
        )

    @extend_schema(request=ScheduleSerializer, responses=WorkOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def schedule(self, request, pk=None):
        s = ScheduleSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        _, warnings = services.schedule(
            tenant=request.tenant, work_order=self.get_object(), request=request, **s.validated_data
        )
        return self._detail(self.get_object(), warnings=warnings)

    @extend_schema(responses=None)
    @action(detail=True, methods=["get"], url_path="suggest-technicians")
    def suggest_technicians(self, request, pk=None):
        wo = self.get_object()
        category_id = wo.ticket.category_id if wo.ticket_id else None
        ranked = selectors.rank_technicians(
            wo.organization,
            category_id=category_id,
            lat=wo.lat,
            lng=wo.lng,
            when=wo.scheduled_start or timezone.now(),
            limit=10,
            include_blocked=True,
        )
        return Response({"weights": selectors.WEIGHTS, "candidates": [score_dict(r) for r in ranked]})

    @extend_schema(responses=StatusLogSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="status-log", pagination_class=None)
    def status_log(self, request, pk=None):
        wo = self.get_object()
        return Response(StatusLogSerializer(wo.status_log.select_related("actor"), many=True).data)

    @extend_schema(methods=["GET"], responses=EvidenceSerializer(many=True))
    @extend_schema(
        methods=["POST"], request={"multipart/form-data": EvidenceUploadSerializer}, responses={201: EvidenceSerializer}
    )
    @action(detail=True, methods=["get", "post"], pagination_class=None)
    def evidence(self, request, pk=None):
        wo = self.get_object()
        if request.method == "POST":
            if not ({"work_orders.manage", "work_orders.execute"} & request.tenant.permissions):
                raise exceptions.PermissionDenied()
            s = EvidenceUploadSerializer(data=request.data)
            s.is_valid(raise_exception=True)
            ev = services.add_evidence(
                tenant=request.tenant,
                work_order=wo,
                upload=s.validated_data["file"],
                kind=s.validated_data["kind"],
                caption=s.validated_data["caption"],
                request=request,
            )
            return Response(EvidenceSerializer(ev).data, status=status.HTTP_201_CREATED)
        return Response(EvidenceSerializer(wo.evidence.select_related("uploaded_by"), many=True).data)


INLINE_SAFE = {"image/png", "image/jpeg", "image/webp", "image/gif"}


@extend_schema(tags=["field service"], responses={(200, "application/octet-stream"): bytes})
class EvidenceDownloadView(APIView):
    permission_classes = [HasPermission(*WO_VIEW, any_of=True)]

    def get(self, request, wo_pk, pk):
        wo = get_object_or_404(selectors.visible_work_orders(request.tenant), pk=wo_pk)
        ev = get_object_or_404(wo.evidence, pk=pk)
        inline = ev.content_type in INLINE_SAFE and request.query_params.get("inline") == "1"
        response = FileResponse(
            ev.file.open("rb"), as_attachment=not inline, filename=ev.original_name, content_type=ev.content_type
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; sandbox"
        response["Cache-Control"] = "private, max-age=300"
        return response


@extend_schema(tags=["field service"])
class ScheduleView(APIView):
    """Appointments and availability blocks for a date range (max 31 days)."""

    permission_classes = [HasPermission("schedule.view")]

    def get(self, request):
        start = parse_datetime(request.query_params.get("start", "") or "")
        end = parse_datetime(request.query_params.get("end", "") or "")
        if not start or not end or end <= start:
            raise exceptions.ValidationError({"start": ["Provide ISO start and end datetimes (end after start)."]})
        if end - start > timedelta(days=31):
            raise exceptions.ValidationError({"end": ["The range may be at most 31 days."]})
        techs = selectors.active_technicians(request.organization)
        if "work_orders.view_all" not in request.tenant.permissions:
            techs = techs.filter(user=request.user)  # technicians see their own calendar
        tech_filter = request.query_params.get("technician")
        if tech_filter:
            techs = techs.filter(pk=tech_filter)
        tech_ids = list(techs.values_list("id", flat=True))
        appts, blocks = selectors.schedule_window(request.organization, start, end, tech_ids)
        return Response(
            {
                "technicians": [{"id": str(t.id), "name": t.user.full_name, "status": t.status} for t in techs],
                "appointments": AppointmentSerializer(appts, many=True).data,
                "availability": [
                    {
                        "id": str(b.id),
                        "technician_id": str(b.technician_id),
                        "type": b.type,
                        "starts_at": b.starts_at,
                        "ends_at": b.ends_at,
                        "note": b.note,
                    }
                    for b in blocks
                ],
            }
        )
