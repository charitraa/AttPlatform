from django.urls import reverse
from django.utils import timezone
from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from apps.assets.models import Asset
from apps.core.fields import OrgScopedPrimaryKeyRelatedField
from apps.customers.models import Customer
from apps.tickets.models import Priority, Ticket, TicketCategory

from .lifecycle import next_steps
from .models import (
    Appointment,
    ServiceArea,
    Skill,
    Technician,
    TechnicianAvailability,
    TechnicianCertification,
    TechnicianSkill,
    WorkOrder,
    WorkOrderEvidence,
    WorkOrderStatusLog,
)

COORD = {"max_digits": 9, "decimal_places": 6, "allow_null": True, "required": False}


def _user(user) -> dict | None:
    return {"id": str(user.id), "full_name": user.full_name, "email": user.email} if user else None


class SkillSerializer(serializers.ModelSerializer):
    ticket_categories = OrgScopedPrimaryKeyRelatedField(
        queryset=TicketCategory.objects.all(), many=True, required=False
    )

    class Meta:
        model = Skill
        fields = ("id", "name", "category", "ticket_categories")

    def validate_name(self, value):
        qs = Skill.objects.filter(organization=self.context["request"].organization, name__iexact=value.strip())
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A skill with this name already exists.")
        return value.strip()


class ServiceAreaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceArea
        fields = ("id", "name", "description", "cities")


class TechnicianSkillSerializer(serializers.ModelSerializer):
    skill = OrgScopedPrimaryKeyRelatedField(queryset=Skill.objects.all())
    name = serializers.CharField(source="skill.name", read_only=True)

    class Meta:
        model = TechnicianSkill
        fields = ("skill", "name", "level")


class CertificationSerializer(serializers.ModelSerializer):
    is_expired = serializers.SerializerMethodField()

    class Meta:
        model = TechnicianCertification
        fields = ("id", "name", "issuer", "number", "issued_at", "expires_at", "is_expired")

    def get_is_expired(self, obj) -> bool:
        return bool(obj.expires_at and obj.expires_at < timezone.localdate())

    def validate(self, attrs):
        if attrs.get("issued_at") and attrs.get("expires_at") and attrs["expires_at"] < attrs["issued_at"]:
            raise serializers.ValidationError({"expires_at": ["Expiry must be after the issue date."]})
        return attrs


class AvailabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = TechnicianAvailability
        fields = ("id", "type", "starts_at", "ends_at", "note")

    def validate(self, attrs):
        if attrs["ends_at"] <= attrs["starts_at"]:
            raise serializers.ValidationError({"ends_at": ["Must be after the start."]})
        return attrs


class TechnicianSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    skills = TechnicianSkillSerializer(many=True, read_only=True)
    service_areas = OrgScopedPrimaryKeyRelatedField(queryset=ServiceArea.objects.all(), many=True, required=False)
    active_jobs = serializers.IntegerField(read_only=True, default=0)
    jobs_today = serializers.IntegerField(read_only=True, default=0)
    home_lat = serializers.DecimalField(**COORD)
    home_lng = serializers.DecimalField(**COORD)

    class Meta:
        model = Technician
        fields = (
            "id",
            "user",
            "employee_id",
            "status",
            "home_lat",
            "home_lng",
            "max_daily_jobs",
            "hourly_cost",
            "currency",
            "location_sharing_enabled",
            "notes",
            "service_areas",
            "skills",
            "active_jobs",
            "jobs_today",
            "created_at",
        )
        read_only_fields = ("id", "location_sharing_enabled", "created_at")

    def get_user(self, obj) -> dict:
        return {**_user(obj.user), "phone": obj.user.phone}

    def validate(self, attrs):
        if (attrs.get("home_lat") is None) != (attrs.get("home_lng") is None) and (
            "home_lat" in attrs or "home_lng" in attrs
        ):
            raise serializers.ValidationError({"home_lat": ["Provide both latitude and longitude, or neither."]})
        if attrs.get("hourly_cost") is not None and not (
            attrs.get("currency") or getattr(self.instance, "currency", "")
        ):
            raise serializers.ValidationError({"currency": ["Set the currency for the hourly cost."]})
        return attrs


class MyProfileSerializer(serializers.ModelSerializer):
    """What technicians may change about themselves."""

    status = serializers.ChoiceField(choices=[Technician.Status.AVAILABLE, Technician.Status.OFF_DUTY])

    class Meta:
        model = Technician
        fields = ("status", "location_sharing_enabled")


class LocationSerializer(serializers.Serializer):
    lat = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-90, max_value=90)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-180, max_value=180)
    accuracy_m = serializers.IntegerField(min_value=0, required=False, allow_null=True)


class EvidenceSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = WorkOrderEvidence
        fields = (
            "id",
            "kind",
            "original_name",
            "content_type",
            "size_bytes",
            "sha256",
            "caption",
            "uploaded_by",
            "created_at",
            "download_url",
        )

    def get_uploaded_by(self, obj) -> dict | None:
        return _user(obj.uploaded_by)

    def get_download_url(self, obj) -> str:
        return reverse("work-order-evidence-download", args=[obj.work_order_id, obj.id])


class EvidenceUploadSerializer(serializers.Serializer):
    file = serializers.FileField(allow_empty_file=False)
    kind = serializers.ChoiceField(choices=WorkOrderEvidence.Kind.choices)
    caption = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")


class StatusLogSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()

    class Meta:
        model = WorkOrderStatusLog
        fields = ("id", "from_status", "to_status", "actor", "note", "lat", "lng", "created_at")

    def get_actor(self, obj) -> dict | None:
        return _user(obj.actor)


class AppointmentSerializer(serializers.ModelSerializer):
    work_order = serializers.SerializerMethodField()
    technician = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = ("id", "work_order", "technician", "starts_at", "ends_at", "status", "notes")

    def get_work_order(self, obj) -> dict:
        wo = obj.work_order
        return {
            "id": str(wo.id),
            "reference": wo.reference,
            "title": wo.title,
            "status": wo.status,
            "priority": wo.priority,
            "customer": wo.customer.name,
            "service_address": wo.service_address,
        }

    def get_technician(self, obj) -> dict:
        return {"id": str(obj.technician_id), "name": obj.technician.user.full_name}


class WorkOrderListSerializer(serializers.ModelSerializer):
    reference = serializers.CharField(read_only=True)
    customer = serializers.SerializerMethodField()
    technician = serializers.SerializerMethodField()
    ticket = serializers.SerializerMethodField()

    class Meta:
        model = WorkOrder
        fields = (
            "id",
            "number",
            "reference",
            "title",
            "status",
            "priority",
            "customer",
            "technician",
            "ticket",
            "service_address",
            "scheduled_start",
            "scheduled_end",
            "customer_confirmed_at",
            "created_at",
            "updated_at",
        )

    def get_customer(self, obj) -> dict:
        return {"id": str(obj.customer_id), "name": obj.customer.name}

    def get_technician(self, obj) -> dict | None:
        t = obj.technician
        return {"id": str(t.id), "user_id": str(t.user_id), "name": t.user.full_name} if t else None

    def get_ticket(self, obj) -> dict | None:
        return {"id": str(obj.ticket_id), "reference": obj.ticket.reference} if obj.ticket_id else None


class WorkOrderDetailSerializer(WorkOrderListSerializer):
    asset = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    next_steps = serializers.SerializerMethodField()
    capabilities = serializers.SerializerMethodField()
    appointment = serializers.SerializerMethodField()
    lat = serializers.DecimalField(**COORD)
    lng = serializers.DecimalField(**COORD)

    class Meta(WorkOrderListSerializer.Meta):
        fields = (
            *WorkOrderListSerializer.Meta.fields,
            "description",
            "asset",
            "lat",
            "lng",
            "actual_start",
            "actual_end",
            "service_notes",
            "completion_summary",
            "parts_used",
            "labor_minutes",
            "labor_cost",
            "parts_cost",
            "currency",
            "customer_signed_by",
            "customer_rating",
            "customer_comment",
            "cancelled_reason",
            "created_by",
            "next_steps",
            "capabilities",
            "appointment",
        )

    def get_asset(self, obj) -> dict | None:
        a = obj.asset
        return (
            {"id": str(a.id), "asset_tag": a.asset_tag, "name": a.name, "serial_number": a.serial_number} if a else None
        )

    def get_created_by(self, obj) -> dict | None:
        return _user(obj.created_by)

    def _ctx(self, obj):
        tenant = self.context["request"].tenant
        mine = bool(obj.technician and obj.technician.user_id == tenant.membership.user.id)
        return tenant.permissions, mine

    def get_next_steps(self, obj) -> list[str]:
        perms, mine = self._ctx(obj)
        return next_steps(
            obj.status,
            is_assigned_technician=mine and "work_orders.execute" in perms,
            can_manage="work_orders.manage" in perms,
        )

    def get_capabilities(self, obj) -> dict:
        perms, mine = self._ctx(obj)
        manage = "work_orders.manage" in perms
        open_ = obj.status not in ("completed", "cancelled")
        return {
            "edit": manage and open_,
            "assign": manage and obj.status in ("created", "assigned", "accepted"),
            "schedule": manage and open_ and obj.technician_id is not None,
            "decline": mine and obj.status in ("assigned", "accepted"),
            "add_evidence": (manage or mine) and obj.status != "cancelled",
            "confirm": (manage or mine) and obj.status == "completed" and not obj.customer_confirmed_at,
        }

    def get_appointment(self, obj) -> dict | None:
        appt = next((a for a in obj.appointments.all() if a.status == "confirmed"), None)
        return (
            {"id": str(appt.id), "starts_at": appt.starts_at, "ends_at": appt.ends_at, "notes": appt.notes}
            if appt
            else None
        )


class WorkOrderCreateSerializer(serializers.Serializer):
    ticket = OrgScopedPrimaryKeyRelatedField(queryset=Ticket.objects.all(), required=False, allow_null=True)
    customer = OrgScopedPrimaryKeyRelatedField(
        queryset=Customer.objects.filter(archived_at__isnull=True), required=False, allow_null=True
    )
    asset = OrgScopedPrimaryKeyRelatedField(queryset=Asset.objects.all(), required=False, allow_null=True)
    technician = OrgScopedPrimaryKeyRelatedField(queryset=Technician.objects.all(), required=False, allow_null=True)
    title = serializers.CharField(max_length=200, required=False, allow_blank=True)
    description = serializers.CharField(max_length=20000, required=False, allow_blank=True)
    priority = serializers.ChoiceField(choices=Priority.choices, required=False)
    service_address = serializers.CharField(max_length=300, required=False, allow_blank=True)
    lat = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)


class WorkOrderUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(max_length=20000, required=False, allow_blank=True)
    priority = serializers.ChoiceField(choices=Priority.choices, required=False)
    service_address = serializers.CharField(max_length=300, required=False, allow_blank=True)
    lat = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    service_notes = serializers.CharField(required=False, allow_blank=True, max_length=20000)


@extend_schema_serializer(component_name="WorkOrderAssign")
class AssignSerializer(serializers.Serializer):
    technician = OrgScopedPrimaryKeyRelatedField(queryset=Technician.objects.all(), allow_null=True)


class PartSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    quantity = serializers.IntegerField(min_value=1, default=1)
    unit_cost = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, required=False, allow_null=True)


class AdvanceSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["accepted", "en_route", "on_site", "in_progress", "completed"])
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000, default="")
    lat = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    completion_summary = serializers.CharField(required=False, allow_blank=True, max_length=10000)
    service_notes = serializers.CharField(required=False, allow_blank=True, max_length=20000)
    parts_used = PartSerializer(many=True, required=False)
    labor_minutes = serializers.IntegerField(required=False, min_value=1, max_value=24 * 60)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class ConfirmSerializer(serializers.Serializer):
    signed_by = serializers.CharField(max_length=150)
    rating = serializers.IntegerField(min_value=1, max_value=5, required=False, allow_null=True)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")


class ScheduleSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    notes = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")
