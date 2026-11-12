from zoneinfo import available_timezones

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.customers.models import Customer
from apps.tickets.models import Priority, Ticket, TicketCategory

from .business_time import business_seconds_between, validate_schedule
from .models import BusinessHours, Holiday, MetricStatus, SLAEvent, SLAInstance, SLAPolicy, SLATarget
from .services import calendar_for

TIMEZONES = frozenset(available_timezones())


class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = ("date", "name")


class BusinessHoursSerializer(serializers.ModelSerializer):
    holidays = HolidaySerializer(many=True, required=False)
    policies = serializers.SerializerMethodField()

    class Meta:
        model = BusinessHours
        fields = ("id", "name", "timezone", "schedule", "holidays", "policies", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def get_policies(self, obj) -> list[str]:
        return [p.name for p in obj.policies.all()]

    def validate_timezone(self, value):
        if value not in TIMEZONES:
            raise serializers.ValidationError("Unknown time zone.")
        return value

    def validate_schedule(self, value):
        try:
            return validate_schedule(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate_name(self, value):
        org = self.context["request"].organization
        qs = BusinessHours.objects.filter(organization=org, name__iexact=value.strip())
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Another calendar already has this name.")
        return value.strip()

    def validate_holidays(self, value):
        dates = [h["date"] for h in value]
        if len(dates) != len(set(dates)):
            raise serializers.ValidationError("Each date can only be listed once.")
        return value

    @transaction.atomic
    def create(self, validated):
        holidays = validated.pop("holidays", [])
        obj = BusinessHours.objects.create(organization=self.context["request"].organization, **validated)
        Holiday.objects.bulk_create(Holiday(business_hours=obj, **h) for h in holidays)
        return obj

    @transaction.atomic
    def update(self, instance, validated):
        holidays = validated.pop("holidays", None)
        instance = super().update(instance, validated)
        if holidays is not None:
            instance.holidays.all().delete()
            Holiday.objects.bulk_create(Holiday(business_hours=instance, **h) for h in holidays)
        return instance


class TargetSerializer(serializers.ModelSerializer):
    class Meta:
        model = SLATarget
        fields = ("priority", "first_response_minutes", "resolution_minutes", "warning_threshold_pct")

    def validate(self, attrs):
        if attrs["first_response_minutes"] > attrs["resolution_minutes"]:
            raise serializers.ValidationError("First response can't take longer than resolution.")
        return attrs


class ConditionsSerializer(serializers.Serializer):
    categories = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    customer_tiers = serializers.ListField(
        child=serializers.ChoiceField(choices=Customer.Tier.choices), required=False, default=list
    )
    channels = serializers.ListField(
        child=serializers.ChoiceField(choices=Ticket.Channel.choices), required=False, default=list
    )

    def validate_categories(self, value):
        org = self.context["request"].organization
        found = set(TicketCategory.objects.filter(organization=org, id__in=value).values_list("id", flat=True))
        if missing := [str(v) for v in value if v not in found]:
            raise serializers.ValidationError(f"Unknown categories: {', '.join(missing)}.")
        return [str(v) for v in dict.fromkeys(value)]


class SLAPolicySerializer(serializers.ModelSerializer):
    targets = TargetSerializer(many=True)
    conditions = ConditionsSerializer(required=False)
    business_hours = serializers.PrimaryKeyRelatedField(
        queryset=BusinessHours.objects.all(), allow_null=True, required=False
    )
    business_hours_name = serializers.CharField(source="business_hours.name", read_only=True, default=None)

    class Meta:
        model = SLAPolicy
        fields = (
            "id", "name", "description", "is_default", "is_active", "business_hours", "business_hours_name",
            "conditions", "priority_order", "escalate_on_breach", "targets", "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        org = getattr(request, "organization", None)
        fields["business_hours"].queryset = BusinessHours.objects.filter(organization=org)
        return fields

    def validate_name(self, value):
        org = self.context["request"].organization
        qs = SLAPolicy.objects.filter(organization=org, name__iexact=value.strip())
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Another policy already has this name.")
        return value.strip()

    def validate_targets(self, value):
        priorities = [t["priority"] for t in value]
        if len(priorities) != len(set(priorities)):
            raise serializers.ValidationError("Each priority can only have one target.")
        if not value:
            raise serializers.ValidationError("Add a target for at least one priority.")
        return value

    def validate(self, attrs):
        is_default = attrs.get("is_default", self.instance.is_default if self.instance else False)
        if is_default:
            if attrs.get("is_active") is False:
                raise serializers.ValidationError({"is_active": ["The default policy can't be deactivated."]})
            covered = {t["priority"] for t in attrs.get("targets", [])} or (
                set(self.instance.targets.values_list("priority", flat=True)) if self.instance else set()
            )
            if missing := [p for p in Priority.values if p not in covered]:
                raise serializers.ValidationError(
                    {"targets": [f"The default policy needs a target for every priority (missing: {', '.join(missing)})."]}
                )
        elif self.instance and self.instance.is_default and attrs.get("is_default") is False:
            raise serializers.ValidationError({"is_default": ["Make another policy the default instead."]})
        return attrs

    def _save_targets(self, policy, targets):
        policy.targets.all().delete()
        SLATarget.objects.bulk_create(SLATarget(policy=policy, **t) for t in targets)

    def _claim_default(self, policy):
        if policy.is_default:
            SLAPolicy.objects.filter(organization=policy.organization, is_default=True).exclude(pk=policy.pk).update(
                is_default=False, updated_at=timezone.now()
            )

    @transaction.atomic
    def create(self, validated):
        targets = validated.pop("targets")
        org = self.context["request"].organization
        if validated.get("is_default"):
            SLAPolicy.objects.filter(organization=org, is_default=True).update(is_default=False)
        policy = SLAPolicy.objects.create(organization=org, **validated)
        self._save_targets(policy, targets)
        return policy

    @transaction.atomic
    def update(self, instance, validated):
        targets = validated.pop("targets", None)
        if validated.get("is_default") and not instance.is_default:
            SLAPolicy.objects.filter(organization=instance.organization, is_default=True).update(is_default=False)
        instance = super().update(instance, validated)
        if targets is not None:
            self._save_targets(instance, targets)
        self._claim_default(instance)
        return instance


class SLAEventSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.full_name", default=None, read_only=True)

    class Meta:
        model = SLAEvent
        fields = ("id", "type", "metric", "occurred_at", "payload", "actor")


class SLAInstanceSerializer(serializers.ModelSerializer):
    """The SLA clock of one ticket, with remaining working time computed now."""

    events = SLAEventSerializer(many=True, read_only=True)
    paused = serializers.BooleanField(source="is_paused", read_only=True)
    business_hours_name = serializers.CharField(source="business_hours.name", default=None, read_only=True)
    response_remaining_seconds = serializers.SerializerMethodField()
    resolution_remaining_seconds = serializers.SerializerMethodField()

    class Meta:
        model = SLAInstance
        fields = (
            "id", "policy_name", "business_hours_name", "priority", "started_at",
            "response_minutes", "response_due_at", "response_status", "responded_at", "response_remaining_seconds",
            "resolution_minutes", "resolution_due_at", "resolution_status", "resolved_at",
            "resolution_remaining_seconds", "warning_threshold_pct", "paused", "paused_at", "paused_seconds",
            "escalated_at", "events",
        )

    def to_representation(self, obj):
        self._cal = calendar_for(obj.business_hours)  # built once per instance
        return super().to_representation(obj)

    def _until(self, start, due) -> int:
        return int(business_seconds_between(self._cal, start, due))

    def get_response_remaining_seconds(self, obj) -> int | None:
        return None if obj.responded_at else self._until(timezone.now(), obj.response_due_at)

    def get_resolution_remaining_seconds(self, obj) -> int | None:
        if obj.resolution_status == MetricStatus.MET:
            return None
        if obj.is_paused:  # frozen: what was left when the clock stopped
            return self._until(obj.paused_at, obj.resolution_due_at)
        return self._until(timezone.now(), obj.resolution_due_at)


class SLASummarySerializer(serializers.ModelSerializer):
    """Compact SLA state embedded in ticket lists."""

    paused = serializers.BooleanField(source="is_paused", read_only=True)

    class Meta:
        model = SLAInstance
        fields = ("response_status", "response_due_at", "resolution_status", "resolution_due_at", "paused")
