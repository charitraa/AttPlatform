from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import exceptions, mixins, serializers, status, viewsets
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


CHANNEL_HELP = {
    "whatsapp": "Add your mobile number (international format, e.g. +977 98…) to your profile.",
    "sms": "Add your mobile number (international format, e.g. +977 98…) to your profile.",
    "telegram": "Connect your Telegram account.",
}


@extend_schema(tags=["notifications"])
class ChannelsView(APIView):
    """Which channels the organization offers and whether you're set up to receive each one."""

    permission_classes = [IsOrganizationMember]

    @extend_schema(
        responses=inline_serializer(
            "Channel",
            {
                "channel": serializers.CharField(),
                "ready": serializers.BooleanField(),
                "help": serializers.CharField(),
                "detail": serializers.CharField(allow_blank=True),
            },
            many=True,
        )
    )
    def get(self, request):
        from .models import ChatLink

        out = []
        for c in services.channels_for(request.organization):
            ready = c in ("in_app", "email") or bool(services.address_for(request.user, request.organization, c))
            detail = ""
            if c == "telegram" and ready:
                link = ChatLink.objects.filter(user=request.user, organization=request.organization, channel=c).first()
                detail = link.display_name if link else ""
            out.append(
                {"channel": c, "ready": ready, "help": "" if ready else CHANNEL_HELP.get(c, ""), "detail": detail}
            )
        return Response(out)


def _telegram(request):
    from .models import Channel

    integration = services.channel_integration(request.organization, Channel.TELEGRAM)
    if integration is None:
        raise exceptions.ValidationError({"detail": ["Telegram isn't set up for this organization."]})
    return integration


@extend_schema(tags=["notifications"])
class TelegramLinkView(APIView):
    """Start linking your Telegram (returns a t.me link to open), or disconnect it."""

    permission_classes = [IsOrganizationMember]

    @extend_schema(request=None, responses=inline_serializer("TelegramLink", {"url": serializers.URLField()}))
    def post(self, request):
        from apps.integrations.connectors.base import ConnectorError

        from . import telegram

        try:
            url = telegram.start_link(request.user, request.organization, _telegram(request))
        except ConnectorError as exc:
            raise exceptions.ValidationError({"detail": [str(exc)]}) from exc
        return Response({"url": url})

    @extend_schema(request=None, responses={204: None})
    def delete(self, request):
        from .models import ChatLink

        ChatLink.objects.filter(user=request.user, organization=request.organization, channel="telegram").delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["notifications"])
class TelegramCheckView(APIView):
    """Check now whether you've pressed Start in Telegram (instead of waiting for the next minute)."""

    permission_classes = [IsOrganizationMember]

    @extend_schema(request=None, responses=inline_serializer("TelegramCheck", {"linked": serializers.BooleanField()}))
    def post(self, request):
        from . import telegram

        telegram.poll(_telegram(request))
        return Response({"linked": bool(services.address_for(request.user, request.organization, "telegram"))})
