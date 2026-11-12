from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.assets.models import Asset
from apps.organizations.permissions import HasPermission
from apps.tickets import services as ticket_services
from apps.tickets.models import TicketCategory, TicketComment, TicketStatus
from apps.tickets.selectors import customer_ids_for_user, visible_tickets

from . import services
from .models import CustomerFeedback
from .serializers import (
    FeedbackSerializer,
    PortalCommentSerializer,
    PortalTicketCreateSerializer,
    PortalTicketSerializer,
)

PORTAL = [HasPermission("portal.access")]


@extend_schema(tags=["portal"])
class PortalTicketViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Tickets of the signed-in customer's account(s)."""

    permission_classes = PORTAL
    serializer_class = PortalTicketSerializer

    def get_queryset(self):
        qs = (
            visible_tickets(self.request.tenant)
            .filter(archived_at__isnull=True)
            .select_related("category", "asset", "assigned_agent")
            .prefetch_related(
                Prefetch(
                    "feedback",
                    queryset=CustomerFeedback.objects.only(
                        "id", "ticket_id", "submitted_by_id", "rating", "comment", "created_at"
                    ),
                )
            )
            .order_by("-updated_at")
        )
        state = self.request.query_params.get("state")
        if state == "open":
            qs = qs.exclude(status__in=[TicketStatus.RESOLVED, TicketStatus.CLOSED])
        elif state == "done":
            qs = qs.filter(status__in=[TicketStatus.RESOLVED, TicketStatus.CLOSED])
        if term := self.request.query_params.get("search", "").strip():
            qs = qs.filter(title__icontains=term)
        return qs

    def _out(self, ticket, code=status.HTTP_200_OK):
        return Response(
            PortalTicketSerializer(self.get_queryset().get(pk=ticket.pk), context=self.get_serializer_context()).data,
            status=code,
        )

    @extend_schema(request=PortalTicketCreateSerializer, responses={201: PortalTicketSerializer})
    def create(self, request):
        s = PortalTicketCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d, org = s.validated_data, request.organization
        data = {"title": d["title"], "description": d["description"]}
        if d.get("category"):
            data["category"] = get_object_or_404(TicketCategory, organization=org, pk=d["category"], is_active=True)
        if d.get("asset"):
            data["asset"] = get_object_or_404(
                Asset, organization=org, pk=d["asset"], customer_id__in=customer_ids_for_user(request.user, org)
            )
        # The ticket service picks the customer account, contact, channel and priority for portal users.
        ticket = ticket_services.create_ticket(tenant=request.tenant, data=data, request=request)
        return self._out(ticket, status.HTTP_201_CREATED)

    @extend_schema(request=PortalCommentSerializer, responses=PortalCommentSerializer(many=True))
    @action(detail=True, methods=["get", "post"], pagination_class=None)
    def comments(self, request, pk=None):
        ticket = self.get_object()
        if request.method == "POST":
            body = str(request.data.get("body", ""))
            if len(body) > 10000:
                raise exceptions.ValidationError({"body": ["Keep it under 10,000 characters."]})
            if ticket.status == TicketStatus.CLOSED:
                raise exceptions.ValidationError({"body": ["This ticket is closed. Reopen it or raise a new one."]})
            ticket_services.add_comment(
                tenant=request.tenant,
                ticket=ticket,
                body=body,
                visibility=TicketComment.Visibility.PUBLIC,
                request=request,
            )
        comments = ticket.comments.filter(visibility=TicketComment.Visibility.PUBLIC).select_related("author")
        return Response(PortalCommentSerializer(comments.order_by("created_at"), many=True).data)

    def _move(self, request, to_status):
        ticket = self.get_object()
        note = str(request.data.get("note", "")).strip()[:2000]
        ticket_services.transition_ticket(
            tenant=request.tenant, ticket=ticket, to_status=to_status, note=note, request=request
        )
        return self._out(ticket)

    @extend_schema(request=None, responses=PortalTicketSerializer)
    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        """The fix worked: close the ticket."""
        return self._move(request, TicketStatus.CLOSED)

    @extend_schema(request=None, responses=PortalTicketSerializer)
    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        """The problem is back or wasn't fixed. Add a `note` saying what's still wrong."""
        if not str(request.data.get("note", "")).strip():
            raise exceptions.ValidationError({"note": ["Tell us what's still wrong."]})
        return self._move(request, TicketStatus.REOPENED)


@extend_schema(tags=["portal"])
class PortalOptionsView(APIView):
    """Choices for the new-ticket form: active categories and the customer's own assets."""

    permission_classes = PORTAL

    def get(self, request):
        org = request.organization
        cats = TicketCategory.objects.filter(organization=org, is_active=True).order_by("name")
        assets = Asset.objects.filter(organization=org, customer_id__in=customer_ids_for_user(request.user, org))
        return Response(
            {
                "categories": [{"id": str(c.id), "name": c.name} for c in cats],
                "assets": [
                    {"id": str(a.id), "name": a.name, "asset_tag": a.asset_tag} for a in assets.order_by("name")
                ],
            }
        )


@extend_schema(tags=["portal"], request=FeedbackSerializer, responses={201: FeedbackSerializer})
class FeedbackView(APIView):
    permission_classes = PORTAL

    def post(self, request):
        s = FeedbackSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        fb = services.submit_feedback(tenant=request.tenant, data=s.validated_data, request=request)
        return Response({"id": str(fb.id), "rating": fb.rating, "comment": fb.comment}, status=status.HTTP_201_CREATED)
