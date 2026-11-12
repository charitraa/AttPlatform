from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import exceptions, mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.organizations.permissions import HasPermission

from . import services
from .connectors.base import ConnectorError, OutboundMessage
from .models import Integration, WebhookDelivery, WebhookEndpoint, new_signing_secret
from .serializers import (
    IntegrationLogSerializer,
    IntegrationSerializer,
    SendTestSerializer,
    WebhookDeliverySerializer,
    WebhookEndpointSerializer,
    WebhookEventSerializer,
    connector_catalog,
)

MANAGE = [HasPermission("integrations.manage")]
RESULT = inline_serializer("TestResult", {"ok": serializers.BooleanField(), "message": serializers.CharField()})
SECRET_ONCE = inline_serializer("SecretOnce", {"signing_secret": serializers.CharField()})


@extend_schema(tags=["integrations"])
class IntegrationViewSet(viewsets.ModelViewSet):
    """Integrations of the active organization. Secrets are write-only (`secrets`); responses show hints only."""

    permission_classes = MANAGE
    serializer_class = IntegrationSerializer
    pagination_class = None

    def get_queryset(self):
        return Integration.objects.filter(organization=self.request.organization).prefetch_related("credentials")

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        obj = s.save()
        audit.record(
            "integration.created",
            request=request,
            target=obj,
            changes={
                "kind": obj.kind,
                "provider": obj.provider,
                "name": obj.name,
                "secrets_set": sorted((request.data.get("secrets") or {}).keys()),
            },
        )
        data = IntegrationSerializer(obj, context=self.get_serializer_context()).data
        # Generated secrets (e.g. the inbound signing secret) are shown once, now.
        return Response({**data, "generated_secrets": getattr(s, "generated", {})}, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        obj = serializer.save()
        changed = sorted(k for k in serializer.validated_data if k not in ("secrets", "_connector"))
        audit.record(
            "integration.updated",
            request=self.request,
            target=obj,
            changes={"fields": changed, "secrets_set": sorted((self.request.data.get("secrets") or {}).keys())},
        )

    def perform_destroy(self, instance):
        pk, name = instance.pk, instance.name
        instance.delete()
        audit.record(
            "integration.deleted",
            request=self.request,
            target_type="integrations.integration",
            target_id=str(pk),
            changes={"name": name},
        )

    @extend_schema(responses=OpenApiTypes.OBJECT)
    @action(detail=False, methods=["get"])
    def catalog(self, request):
        """Available connectors (settings and secrets they need) and the outbound event types."""
        return Response(
            {
                "connectors": connector_catalog(),
                "events": [{"type": k, "label": v} for k, v in services.EVENT_TYPES.items()],
            }
        )

    @extend_schema(request=None, responses=RESULT)
    @action(detail=True, methods=["post"])
    def test(self, request, pk=None):
        result = services.test_connection(self.get_object())
        return Response({"ok": result.ok, "message": result.message})

    @extend_schema(request=SendTestSerializer, responses=OpenApiTypes.OBJECT)
    @action(detail=True, methods=["post"], url_path="send-test")
    def send_test(self, request, pk=None):
        integration = self.get_object()
        s = SendTestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            result = services.send_message(integration, OutboundMessage(**s.validated_data))
        except ConnectorError as exc:
            raise exceptions.ValidationError({"detail": [str(exc)]}) from exc
        audit.record("integration.test_message_sent", request=request, target=integration, changes={})
        return Response(result)

    @extend_schema(request=None, responses=SECRET_ONCE)
    @action(detail=True, methods=["post"], url_path="rotate-secret")
    def rotate_secret(self, request, pk=None):
        """New inbound signing secret, shown once. The old one stops working immediately."""
        integration = self.get_object()
        if integration.kind != Integration.Kind.INBOUND:
            raise exceptions.ValidationError({"detail": ["Only inbound integrations have a signing secret."]})
        value = new_signing_secret()
        integration.set_secret("signing_secret", value)
        audit.record("integration.secret_rotated", request=request, target=integration, changes={})
        return Response({"signing_secret": value})

    @extend_schema(responses=IntegrationLogSerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=viewsets.ModelViewSet.pagination_class)
    def logs(self, request, pk=None):
        qs = self.get_object().logs.all()
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(IntegrationLogSerializer(page, many=True).data)

    @extend_schema(responses=WebhookDeliverySerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=viewsets.ModelViewSet.pagination_class)
    def deliveries(self, request, pk=None):
        qs = WebhookDelivery.objects.filter(endpoint__integration=self.get_object()).select_related("endpoint")
        if s := request.query_params.get("status"):
            qs = qs.filter(status=s)
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(WebhookDeliverySerializer(page, many=True).data)

    @extend_schema(responses=WebhookEventSerializer(many=True))
    @action(
        detail=True, methods=["get"], url_path="inbound-events", pagination_class=viewsets.ModelViewSet.pagination_class
    )
    def inbound_events(self, request, pk=None):
        page = self.paginate_queryset(self.get_object().inbound_events.all())
        return self.get_paginated_response(WebhookEventSerializer(page, many=True).data)

    @extend_schema(request=WebhookEndpointSerializer, responses=WebhookEndpointSerializer(many=True))
    @action(detail=True, methods=["get", "post"])
    def endpoints(self, request, pk=None):
        integration = self.get_object()
        if request.method == "GET":
            return Response(WebhookEndpointSerializer(integration.endpoints.all(), many=True).data)
        if integration.kind != Integration.Kind.WEBHOOK:
            raise exceptions.ValidationError({"detail": ["Endpoints belong to outbound webhook integrations."]})
        s = WebhookEndpointSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        endpoint = WebhookEndpoint(integration=integration, **s.validated_data)
        secret = endpoint.rotate_signing_secret()
        endpoint.save()
        audit.record(
            "webhook_endpoint.created",
            request=request,
            target=endpoint,
            changes={"url": endpoint.url, "events": endpoint.events},
        )
        return Response(
            {**WebhookEndpointSerializer(endpoint).data, "signing_secret": secret}, status=status.HTTP_201_CREATED
        )


@extend_schema(tags=["integrations"])
class WebhookEndpointViewSet(mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    permission_classes = MANAGE
    serializer_class = WebhookEndpointSerializer

    def get_queryset(self):
        return WebhookEndpoint.objects.filter(integration__organization=self.request.organization)

    def perform_update(self, serializer):
        obj = serializer.save()
        audit.record(
            "webhook_endpoint.updated",
            request=self.request,
            target=obj,
            changes={"fields": sorted(serializer.validated_data)},
        )

    def perform_destroy(self, instance):
        audit.record("webhook_endpoint.deleted", request=self.request, target=instance, changes={"url": instance.url})
        instance.delete()

    @extend_schema(request=None, responses=SECRET_ONCE)
    @action(detail=True, methods=["post"], url_path="rotate-secret")
    def rotate_secret(self, request, pk=None):
        endpoint = self.get_object()
        value = endpoint.rotate_signing_secret()
        endpoint.save(update_fields=["signing_secret_ciphertext", "updated_at"])
        audit.record("webhook_endpoint.secret_rotated", request=request, target=endpoint, changes={})
        return Response({"signing_secret": value})


@extend_schema(tags=["integrations"])
class WebhookDeliveryViewSet(viewsets.GenericViewSet):
    permission_classes = MANAGE
    serializer_class = WebhookDeliverySerializer

    def get_queryset(self):
        return WebhookDelivery.objects.filter(endpoint__integration__organization=self.request.organization)

    @extend_schema(request=None, responses=WebhookDeliverySerializer)
    @action(detail=True, methods=["post"])
    def redeliver(self, request, pk=None):
        d = services.redeliver(self.get_object())
        audit.record("webhook_delivery.redelivered", request=request, target=d, changes={"event_id": str(d.event_id)})
        return Response(WebhookDeliverySerializer(d).data, status=status.HTTP_202_ACCEPTED)


class InboundThrottle(SimpleRateThrottle):
    scope = "inbound_webhook"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": str(view.kwargs.get("integration_id"))}


@extend_schema(
    tags=["integrations"],
    request=OpenApiTypes.OBJECT,
    responses={
        202: inline_serializer(
            "InboundAccepted",
            {"id": serializers.UUIDField(), "status": serializers.CharField(), "duplicate": serializers.BooleanField()},
        )
    },
)
class InboundWebhookView(APIView):
    """
    Signed, unauthenticated entry point for external systems. The body is JSON with a unique
    `id`; sign it with the integration's signing secret (`X-ATT-Signature: t=…,v1=…`).
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [InboundThrottle]

    def post(self, request, integration_id):
        headers = {k.lower(): v for k, v in request.headers.items()}
        try:
            event, created = services.receive(integration_id, body=request.body, headers=headers)
        except services.InboundRejected as exc:
            return Response({"error": {"code": "rejected", "message": exc.message}}, status=exc.status)
        return Response(
            {"id": str(event.id), "status": event.status, "duplicate": not created},
            status=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK,
        )
