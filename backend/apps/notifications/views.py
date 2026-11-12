from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.permissions import IsOrganizationMember

from . import services
from .models import NotificationType
from .serializers import MarkReadSerializer, NotificationSerializer, PreferenceSerializer

COUNT = inline_serializer("UnreadCount", {"unread": serializers.IntegerField()})


@extend_schema(tags=["notifications"])
class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Your in-app notifications in the active organization (newest first)."""

    permission_classes = [IsOrganizationMember]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        qs = services.inbox(self.request.user, self.request.organization)
        if self.action == "list" and self.request.query_params.get("unread") in ("1", "true"):
            qs = qs.filter(read_at__isnull=True)
        return qs

    @extend_schema(parameters=[OpenApiParameter("unread", bool, description="Only unread notifications.")])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(responses=COUNT)
    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        return Response({"unread": self.get_queryset().filter(read_at__isnull=True).count()})

    @extend_schema(request=None, responses=NotificationSerializer)
    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        n = get_object_or_404(self.get_queryset(), pk=pk)
        if n.read_at is None:
            services.mark_read(request.user, request.organization, ids=[n.pk])
            n.read_at = timezone.now()
        return Response(NotificationSerializer(n).data)

    @extend_schema(request=MarkReadSerializer, responses=COUNT)
    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        s = MarkReadSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        services.mark_read(request.user, request.organization, ids=s.validated_data.get("ids"))
        return Response({"unread": self.get_queryset().filter(read_at__isnull=True).count()})


def _flatten(prefs: dict, channels: list[str]) -> list[dict]:
    labels = dict(NotificationType.choices)
    return [
        {"type": t, "label": labels[t], "channel": c, "enabled": prefs[t][c]}
        for t in NotificationType.values
        for c in channels
    ]


@extend_schema(tags=["notifications"])
class PreferencesView(APIView):
    """Which notifications you get, per type and channel (defaults apply until you change one)."""

    permission_classes = [IsOrganizationMember]

    @extend_schema(responses=PreferenceSerializer(many=True))
    def get(self, request):
        return Response(
            _flatten(
                services.preferences_for(request.user, request.organization),
                services.channels_for(request.organization),
            )
        )

    @extend_schema(request=PreferenceSerializer(many=True), responses=PreferenceSerializer(many=True))
    def put(self, request):
        s = PreferenceSerializer(data=request.data, many=True)
        s.is_valid(raise_exception=True)
        prefs = services.set_preferences(request.user, request.organization, s.validated_data)
        return Response(_flatten(prefs, services.channels_for(request.organization)), status=status.HTTP_200_OK)
