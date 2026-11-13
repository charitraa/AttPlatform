import re

from django.contrib.postgres.search import SearchQuery, SearchVector
from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters import rest_framework as filters
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.permissions import HasPermission, IsOrganizationMember, MethodPermissions

from . import selectors, services
from .models import ACTIVE_STATUSES, Ticket, TicketCategory
from .serializers import (
    AssignSerializer,
    AttachmentSerializer,
    AttachmentUploadSerializer,
    CommentCreateSerializer,
    CommentSerializer,
    EscalateSerializer,
    HistorySerializer,
    TicketCategorySerializer,
    TicketCreateSerializer,
    TicketDetailSerializer,
    TicketListSerializer,
    TicketUpdateSerializer,
    TransitionSerializer,
)

VIEW = ["tickets.view_all", "tickets.view_own"]
NUMBER_RE = re.compile(r"^(?:tck-?)?0*(\d{1,9})$", re.IGNORECASE)


class CSVChoiceFilter(filters.BaseInFilter, filters.CharFilter):
    """`?status=open,assigned`"""


class TicketFilter(filters.FilterSet):
    status = filters.CharFilter(method="filter_status", help_text="Comma-separated statuses, or `active`.")
    priority = CSVChoiceFilter(field_name="priority", lookup_expr="in")
    category = filters.UUIDFilter(field_name="category_id")
    customer = filters.UUIDFilter(field_name="customer_id")
    asset = filters.UUIDFilter(field_name="asset_id")
    assigned_agent = filters.CharFilter(method="filter_assignee", help_text="User ID, `me` or `none`.")
    assigned_technician = filters.CharFilter(method="filter_assignee", help_text="User ID, `me` or `none`.")
    created_after = filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_before = filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lte")
    overdue = filters.BooleanFilter(method="filter_overdue")
    tag = filters.CharFilter(field_name="tags", lookup_expr="contains", method="filter_tag")
    archived = filters.ChoiceFilter(
        choices=[("false", "false"), ("true", "true"), ("all", "all")], method="filter_archived"
    )

    class Meta:
        model = Ticket
        fields = ()

    def filter_status(self, qs, name, value):
        values = {v.strip() for v in value.split(",") if v.strip()}
        if "active" in values:
            values = (values - {"active"}) | set(ACTIVE_STATUSES)
        return qs.filter(status__in=values)

    def filter_assignee(self, qs, name, value):
        if value == "none":
            return qs.filter(**{f"{name}__isnull": True})
        if value == "me":
            return qs.filter(**{name: self.request.user})
        return qs.filter(**{f"{name}_id": value})

    def filter_overdue(self, qs, name, value):
        cond = Q(due_at__lt=timezone.now(), status__in=ACTIVE_STATUSES)
        return qs.filter(cond) if value else qs.exclude(cond)

    def filter_tag(self, qs, name, value):
        return qs.filter(tags__contains=[value.lower()])

    def filter_archived(self, qs, name, value):
        return qs if value == "all" else qs.filter(archived_at__isnull=(value == "false"))

    @property
    def qs(self):
        qs = super().qs
        if "archived" not in self.data:
            qs = qs.filter(archived_at__isnull=True)  # archived tickets are hidden unless asked for
        return qs


class TicketOrdering(OrderingFilter):
    """Priority sorts by severity (critical first when descending), not alphabetically."""

    def filter_queryset(self, request, queryset, view):
        ordering = self.get_ordering(request, queryset, view)
        if not ordering:
            return queryset
        if any(o.lstrip("-") == "priority" for o in ordering):
            queryset = queryset.annotate(priority_rank=selectors.priority_rank_expression())
            ordering = [o.replace("priority", "priority_rank") for o in ordering]
        return queryset.order_by(*ordering, "-created_at")


def search_tickets(qs, term: str):
    term = term.strip()
    if not term:
        return qs
    match = NUMBER_RE.match(term)
    if match:
        return qs.filter(number=int(match.group(1)))
    vector = SearchVector("title", "description", config="english")  # matches the GIN expression index
    query = SearchQuery(term, search_type="websearch", config="english")
    return qs.annotate(search=vector).filter(
        Q(search=query) | Q(title__icontains=term) | Q(customer__name__icontains=term)
    )


@extend_schema(tags=["tickets"])
class TicketViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    filterset_class = TicketFilter
    filter_backends = [filters.DjangoFilterBackend, TicketOrdering]
    ordering_fields = ("created_at", "updated_at", "due_at", "number", "priority", "status")
    ordering = ("-created_at",)
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    # Per-action permission requirements (any-of). Row-level visibility comes from the queryset.
    action_permissions = {
        "list": VIEW,
        "retrieve": VIEW,
        "comments": VIEW,
        "attachments": VIEW,
        "history": VIEW,
        "create": ["tickets.create"],
        "partial_update": ["tickets.update"],
        "transition": ["tickets.update", "portal.access"],  # customers: confirm/reopen only (service-enforced)
        "assign": ["tickets.assign"],
        "escalate": ["tickets.update"],
        "archive": ["tickets.archive"],
        "unarchive": ["tickets.archive"],
    }

    def get_permissions(self):
        codes = self.action_permissions.get(self.action)
        return [HasPermission(*codes, any_of=True)()] if codes else [IsOrganizationMember()]

    queryset = Ticket.objects.none()  # for the API schema only; get_queryset() scopes every request

    def get_queryset(self):
        qs = selectors.with_detail_relations(selectors.visible_tickets(self.request.tenant)).select_related("sla")
        if self.action == "list":
            qs = search_tickets(qs, self.request.query_params.get("search", ""))
        return qs

    def get_serializer_class(self):
        return TicketListSerializer if self.action == "list" else TicketDetailSerializer

    def filter_queryset(self, queryset):
        # List filters (incl. "hide archived") must not affect detail actions: DRF also
        # runs filter backends inside get_object(), which would 404 archived tickets.
        return super().filter_queryset(queryset) if self.action == "list" else queryset

    def _detail(self, ticket, status_code=status.HTTP_200_OK):
        fresh = (
            self.get_queryset().get(pk=ticket.pk)
            if self.action != "create"
            else (selectors.with_detail_relations(Ticket.objects.filter(pk=ticket.pk)).get())
        )
        return Response(TicketDetailSerializer(fresh, context=self.get_serializer_context()).data, status=status_code)

    @extend_schema(parameters=[OpenApiParameter("search", str, description="Text, or a ticket number like TCK-42")])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=TicketCreateSerializer, responses={201: TicketDetailSerializer})
    def create(self, request, *args, **kwargs):
        s = TicketCreateSerializer(data=request.data, context=self.get_serializer_context())
        s.is_valid(raise_exception=True)
        ticket = services.create_ticket(tenant=request.tenant, data=s.validated_data, request=request)
        return self._detail(ticket, status.HTTP_201_CREATED)

    @extend_schema(request=TicketUpdateSerializer, responses=TicketDetailSerializer)
    def partial_update(self, request, pk=None):
        s = TicketUpdateSerializer(data=request.data, context=self.get_serializer_context())
        s.is_valid(raise_exception=True)
        ticket = services.update_ticket(
            tenant=request.tenant, ticket=self.get_object(), data=s.validated_data, request=request
        )
        return self._detail(ticket)

    @extend_schema(request=TransitionSerializer, responses=TicketDetailSerializer)
    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        s = TransitionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        ticket = services.transition_ticket(
            tenant=request.tenant,
            ticket=self.get_object(),
            to_status=s.validated_data["status"],
            note=s.validated_data["note"],
            resolution_notes=s.validated_data.get("resolution_notes"),
            request=request,
        )
        return self._detail(ticket)

    @extend_schema(request=AssignSerializer, responses=TicketDetailSerializer)
    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        s = AssignSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        ticket = services.assign_ticket(
            tenant=request.tenant,
            ticket=self.get_object(),
            agent_id=s.validated_data.get("agent", services.UNSET),
            technician_id=s.validated_data.get("technician", services.UNSET),
            request=request,
        )
        return self._detail(ticket)

    @extend_schema(request=EscalateSerializer, responses=TicketDetailSerializer)
    @action(detail=True, methods=["post"])
    def escalate(self, request, pk=None):
        s = EscalateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        ticket = services.escalate_ticket(
            tenant=request.tenant, ticket=self.get_object(), reason=s.validated_data["reason"], request=request
        )
        return self._detail(ticket)

    @extend_schema(request=None, responses=TicketDetailSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        ticket = services.set_archived(tenant=request.tenant, ticket=self.get_object(), archived=True, request=request)
        return self._detail(ticket)

    @extend_schema(request=None, responses=TicketDetailSerializer)
    @action(detail=True, methods=["post"])
    def unarchive(self, request, pk=None):
        ticket = services.set_archived(tenant=request.tenant, ticket=self.get_object(), archived=False, request=request)
        return self._detail(ticket)

    @extend_schema(methods=["GET"], responses=CommentSerializer(many=True))
    @extend_schema(methods=["POST"], request=CommentCreateSerializer, responses={201: CommentSerializer})
    @action(detail=True, methods=["get", "post"], pagination_class=None)
    def comments(self, request, pk=None):
        ticket = self.get_object()
        if request.method == "POST":
            s = CommentCreateSerializer(data=request.data)
            s.is_valid(raise_exception=True)
            comment = services.add_comment(tenant=request.tenant, ticket=ticket, request=request, **s.validated_data)
            return Response(CommentSerializer(comment).data, status=status.HTTP_201_CREATED)
        return Response(CommentSerializer(selectors.visible_comments(ticket, request.tenant), many=True).data)

    @extend_schema(methods=["GET"], responses=AttachmentSerializer(many=True))
    @extend_schema(
        methods=["POST"],
        request={"multipart/form-data": AttachmentUploadSerializer},
        responses={201: AttachmentSerializer},
    )
    @action(detail=True, methods=["get", "post"], pagination_class=None)
    def attachments(self, request, pk=None):
        ticket = self.get_object()
        if request.method == "POST":
            s = AttachmentUploadSerializer(data=request.data)
            s.is_valid(raise_exception=True)
            attachment = services.add_attachment(
                tenant=request.tenant,
                ticket=ticket,
                upload=s.validated_data["file"],
                visibility=s.validated_data["visibility"],
                request=request,
            )
            return Response(AttachmentSerializer(attachment).data, status=status.HTTP_201_CREATED)
        return Response(AttachmentSerializer(selectors.visible_attachments(ticket, request.tenant), many=True).data)

    @extend_schema(responses=HistorySerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=None)
    def history(self, request, pk=None):
        ticket = self.get_object()
        return Response(HistorySerializer(selectors.visible_history(ticket, request.tenant), many=True).data)


# Inline display is only allowed for raster images; everything else downloads.
INLINE_SAFE = {"image/png", "image/jpeg", "image/webp", "image/gif"}


@extend_schema(tags=["tickets"], responses={(200, "application/octet-stream"): bytes})
class AttachmentDownloadView(APIView):
    """Authenticated, permission-checked file access. Files are never served directly by the web server."""

    permission_classes = [HasPermission(*VIEW, any_of=True)]

    def get(self, request, ticket_pk, pk):
        ticket = get_object_or_404(selectors.visible_tickets(request.tenant), pk=ticket_pk)
        attachment = get_object_or_404(selectors.visible_attachments(ticket, request.tenant), pk=pk)
        inline = attachment.content_type in INLINE_SAFE and request.query_params.get("inline") == "1"
        response = FileResponse(
            attachment.file.open("rb"),
            as_attachment=not inline,
            filename=attachment.original_name,
            content_type=attachment.content_type,
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; sandbox"
        response["Cache-Control"] = "private, max-age=300"
        return response


@extend_schema(tags=["tickets"])
class TicketCategoryViewSet(viewsets.ModelViewSet):
    """Readable by every member (needed to raise tickets); managed by organization admins."""

    permission_classes = [MethodPermissions]
    method_permissions = {
        "GET": ["organization.view"],
        "POST": ["organization.manage"],
        "PATCH": ["organization.manage"],
        "PUT": ["organization.manage"],
        "DELETE": ["organization.manage"],
    }
    serializer_class = TicketCategorySerializer
    pagination_class = None

    queryset = TicketCategory.objects.none()  # for the API schema only; get_queryset() scopes every request

    def get_queryset(self):
        qs = TicketCategory.objects.filter(organization=self.request.organization).select_related("parent")
        if self.request.query_params.get("include_inactive") != "true":
            qs = qs.filter(is_active=True)
        return qs

    def perform_create(self, serializer):
        serializer.save(organization=self.request.organization)

    def perform_destroy(self, instance):
        # Categories in use are deactivated rather than deleted so history stays intact.
        if instance.tickets.exists() or instance.children.exists():
            instance.is_active = False
            instance.save(update_fields=["is_active", "updated_at"])
        else:
            instance.delete()
