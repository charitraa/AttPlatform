from django.conf import settings
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import health
from .serializers import HealthSerializer, MetaSerializer, ReadinessSerializer


class PublicAPIView(APIView):
    """Unauthenticated endpoint. Must never expose tenant data or secrets."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "system"


class HealthView(PublicAPIView):
    """Liveness: the process is up and serving requests (no dependency checks)."""

    @extend_schema(responses=HealthSerializer, tags=["system"])
    def get(self, request):
        return Response({"status": "ok", "version": settings.APP_VERSION, "timestamp": timezone.now()})


class ReadinessView(PublicAPIView):
    """Readiness: database and Redis are reachable. 503 if any dependency fails."""

    @extend_schema(responses={200: ReadinessSerializer, 503: ReadinessSerializer}, tags=["system"])
    def get(self, request):
        checks = health.run_checks()
        healthy = all(c["status"] == "ok" for c in checks.values())
        return Response(
            {"status": "ok" if healthy else "degraded", "checks": checks},
            status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class MetaView(PublicAPIView):
    """Public client configuration. Contains no secrets — only whether AI is mocked."""

    @extend_schema(responses=MetaSerializer, tags=["system"])
    def get(self, request):
        return Response(
            {
                "name": "ATT Platform",
                "version": settings.APP_VERSION,
                "environment": settings.ENVIRONMENT,
                "ai_provider": settings.AI_PROVIDER,
                "ai_mock_mode": settings.AI_PROVIDER == "mock",
                "features": {"websockets": True, "ai": True, "registration": settings.REGISTRATION_ENABLED},
            }
        )
