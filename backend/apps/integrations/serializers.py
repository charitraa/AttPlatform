from django.conf import settings
from django.db import transaction
from rest_framework import serializers

from . import net
from .connectors import catalog, connector_class
from .models import Integration, IntegrationLog, WebhookDelivery, WebhookEndpoint, WebhookEvent, new_signing_secret
from .services import EVENT_TYPES


def inbound_url(integration: Integration) -> str:
    base = getattr(settings, "PUBLIC_API_URL", "") or settings.FRONTEND_URL
    return f"{base.rstrip('/')}/api/v1/webhooks/inbound/{integration.id}/"


class ConnectorSerializer(serializers.Serializer):
    """The catalog entry the UI renders a form from."""

    def to_representation(self, cls):
        def field(f):
            return {
                "name": f.name,
                "label": f.label,
                "required": f.required,
                "help": f.help,
                "kind": f.kind,
                "choices": list(f.choices),
            }

        return {
            "kind": cls.kind,
            "provider": cls.provider,
            "label": cls.label,
            "description": cls.description,
            "fields": [field(f) for f in cls.fields],
            "secrets": [field(f) for f in cls.secrets],
            "generated_secrets": list(cls.generated_secrets),
            "can_send": cls.can_send,
            "receives": cls.receives,
        }


class IntegrationSerializer(serializers.ModelSerializer):
    secrets = serializers.DictField(
        child=serializers.CharField(max_length=2000, trim_whitespace=True),
        write_only=True,
        required=False,
        help_text="Write-only. Keys from the connector's `secrets`; never returned.",
    )
    credentials = serializers.SerializerMethodField()
    health = serializers.CharField(read_only=True)
    label = serializers.SerializerMethodField()
    inbound_url = serializers.SerializerMethodField()
    endpoint_count = serializers.SerializerMethodField()

    class Meta:
        model = Integration
        fields = (
            "id",
            "kind",
            "provider",
            "label",
            "name",
            "config",
            "is_enabled",
            "health",
            "last_success_at",
            "last_error_at",
            "last_error",
            "credentials",
            "secrets",
            "inbound_url",
            "endpoint_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "last_success_at", "last_error_at", "last_error", "created_at", "updated_at")

    def get_label(self, obj) -> str:
        cls = connector_class(obj.kind, obj.provider)
        return cls.label if cls else obj.provider

    def get_credentials(self, obj) -> dict:
        """What's configured, never the value: {"auth_token": {"configured": true, "hint": "…a1b2"}}."""
        cls = connector_class(obj.kind, obj.provider)
        stored = {c.key: c.hint for c in obj.credentials.all()}
        names = [f.name for f in cls.secrets] + list(cls.generated_secrets) if cls else list(stored)
        return {n: {"configured": n in stored, "hint": stored.get(n, "")} for n in names}

    def get_inbound_url(self, obj) -> str | None:
        return inbound_url(obj) if obj.kind == Integration.Kind.INBOUND else None

    def get_endpoint_count(self, obj) -> int | None:
        return obj.endpoints.count() if obj.kind == Integration.Kind.WEBHOOK else None

    def validate(self, attrs):
        if self.instance:  # kind/provider are fixed after creation
            if any(k in attrs and attrs[k] != getattr(self.instance, k) for k in ("kind", "provider")):
                raise serializers.ValidationError(
                    {"provider": ["The connector can't be changed. Create a new integration."]}
                )
            kind, provider = self.instance.kind, self.instance.provider
        else:
            kind, provider = attrs.get("kind"), attrs.get("provider")
        cls = connector_class(kind or "", provider or "")
        if cls is None:
            raise serializers.ValidationError({"provider": ["Unknown connector."]})
        if "config" in attrs or not self.instance:
            try:
                attrs["config"] = cls.validate_config(attrs.get("config") or {})
            except ValueError as exc:
                raise serializers.ValidationError({"config": exc.args[0]}) from exc
            if default_customer := attrs["config"].get("default_customer_id"):
                from apps.customers.models import Customer

                if not Customer.objects.filter(
                    organization=self.context["request"].organization, pk=default_customer
                ).exists():
                    raise serializers.ValidationError({"config": {"default_customer_id": ["Unknown customer."]}})
        allowed = {f.name for f in cls.secrets}
        given = attrs.get("secrets") or {}
        if unknown := set(given) - allowed:
            raise serializers.ValidationError({"secrets": [f"Unknown secrets: {', '.join(sorted(unknown))}."]})
        if not self.instance:
            missing = [f.name for f in cls.secrets if f.required and not given.get(f.name)]
            if missing:
                raise serializers.ValidationError({"secrets": [f"Required: {', '.join(missing)}."]})
        name = (attrs.get("name") or (self.instance.name if self.instance else "")).strip()
        qs = Integration.objects.filter(organization=self.context["request"].organization, name__iexact=name)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError({"name": ["Another integration already has this name."]})
        attrs["_connector"] = cls
        return attrs

    @transaction.atomic
    def create(self, validated):
        cls = validated.pop("_connector")
        secrets = validated.pop("secrets", {})
        request = self.context["request"]
        obj = Integration.objects.create(organization=request.organization, created_by=request.user, **validated)
        for k, v in secrets.items():
            obj.set_secret(k, v)
        self.generated = {}
        for key in cls.generated_secrets:
            value = new_signing_secret()
            obj.set_secret(key, value)
            self.generated[key] = value
        return obj

    @transaction.atomic
    def update(self, instance, validated):
        validated.pop("_connector")
        secrets = validated.pop("secrets", {})
        instance = super().update(instance, validated)
        for k, v in secrets.items():
            if v:  # empty means "leave unchanged"
                instance.set_secret(k, v)
        return instance


class WebhookEndpointSerializer(serializers.ModelSerializer):
    events = serializers.ListField(child=serializers.ChoiceField(choices=sorted(EVENT_TYPES)), allow_empty=False)
    stats = serializers.SerializerMethodField()

    class Meta:
        model = WebhookEndpoint
        fields = ("id", "url", "events", "is_active", "description", "stats", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def get_stats(self, obj) -> dict:
        last = obj.deliveries.order_by("-created_at").first()
        return {
            "failed": obj.deliveries.filter(status=WebhookDelivery.Status.FAILED).count(),
            "last_status": last.status if last else None,
            "last_at": last.created_at if last else None,
        }

    def validate_url(self, value):
        try:
            net.validate_public_url(value)
        except net.UnsafeURL as exc:
            raise serializers.ValidationError(str(exc)) from exc
        except net.EgressError as exc:
            raise serializers.ValidationError(f"Can't reach that host: {exc}") from exc
        return value

    def validate_events(self, value):
        return sorted(set(value))


class WebhookDeliverySerializer(serializers.ModelSerializer):
    url = serializers.CharField(source="endpoint.url", read_only=True)

    class Meta:
        model = WebhookDelivery
        fields = (
            "id",
            "event_id",
            "event_type",
            "url",
            "status",
            "attempts",
            "next_retry_at",
            "response_code",
            "response_body",
            "error",
            "delivered_at",
            "payload",
            "created_at",
        )


class WebhookEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookEvent
        fields = ("id", "external_id", "status", "result", "error", "payload", "created_at", "processed_at")


class IntegrationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrationLog
        fields = (
            "id",
            "direction",
            "operation",
            "status",
            "duration_ms",
            "request_summary",
            "response_summary",
            "error",
            "created_at",
        )


class SendTestSerializer(serializers.Serializer):
    to = serializers.RegexField(r"^\+[1-9]\d{6,14}$", help_text="E.164 phone number, e.g. +9779812345678")
    text = serializers.CharField(max_length=600, required=False, allow_blank=True, default="")
    template = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    variables = serializers.ListField(child=serializers.CharField(max_length=100), required=False, default=list)


def connector_catalog() -> list[dict]:
    return [ConnectorSerializer(cls).data for cls in catalog()]
