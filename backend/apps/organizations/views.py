from django.db.models import Q
from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog

from . import services
from .models import Invitation, Membership, Role
from .permissions import HasPermission, MethodPermissions
from .serializers import (
    AuditLogSerializer,
    InvitationCreateSerializer,
    InvitationSerializer,
    MemberSerializer,
    MemberUpdateSerializer,
    OrganizationSerializer,
    RoleSerializer,
)


@extend_schema(tags=["organization"])
class OrganizationView(APIView):
    """The caller's current organization."""

    permission_classes = [MethodPermissions]
    method_permissions = {"GET": ["organization.view"], "PATCH": ["organization.manage"]}

    @extend_schema(responses=OrganizationSerializer)
    def get(self, request):
        return Response(OrganizationSerializer(request.organization).data)

    @extend_schema(request=OrganizationSerializer, responses=OrganizationSerializer)
    def patch(self, request):
        s = OrganizationSerializer(request.organization, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        org = services.update_organization(organization=request.organization, data=s.validated_data, request=request)
        return Response(OrganizationSerializer(org).data)


@extend_schema(tags=["organization"])
class RoleViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [HasPermission("roles.view")]
    serializer_class = RoleSerializer
    pagination_class = None
    lookup_field = "code"

    def get_queryset(self):
        return Role.objects.filter(Q(organization__isnull=True) | Q(organization=self.request.organization))

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if getattr(self.request, "membership", None):
            ctx["assignable_codes"] = set(services.assignable_role_codes(self.request.membership))
        return ctx


class MemberFilter(filters.FilterSet):
    role = filters.CharFilter(field_name="role__code")
    is_active = filters.BooleanFilter()

    class Meta:
        model = Membership
        fields = ("role", "is_active")


@extend_schema(tags=["organization"])
class MemberViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Users of the current organization, addressed by user ID. Role and status
    changes go through PATCH; DELETE deactivates (memberships are never hard-deleted).
    """

    permission_classes = [MethodPermissions]
    method_permissions = {"GET": ["users.view"], "PATCH": ["users.manage"], "DELETE": ["users.manage"]}
    serializer_class = MemberSerializer
    lookup_field = "user__id"
    lookup_url_kwarg = "pk"
    filterset_class = MemberFilter
    search_fields = ("user__email", "user__first_name", "user__last_name")
    ordering_fields = ("created_at", "user__email", "user__first_name")
    ordering = ("user__first_name", "user__email")

    def get_queryset(self):
        return Membership.objects.filter(organization=self.request.organization).select_related("user", "role")

    @extend_schema(request=MemberUpdateSerializer, responses=MemberSerializer)
    def partial_update(self, request, pk=None):
        s = MemberUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        member = services.change_member(
            actor=request.membership,
            target=self.get_object(),
            role_code=s.validated_data.get("role"),
            is_active=s.validated_data.get("is_active"),
            request=request,
        )
        return Response(MemberSerializer(member).data)

    @extend_schema(responses={204: None})
    def destroy(self, request, pk=None):
        services.change_member(actor=request.membership, target=self.get_object(), is_active=False, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class InvitationFilter(filters.FilterSet):
    status = filters.ChoiceFilter(
        choices=[("pending", "pending"), ("accepted", "accepted"), ("revoked", "revoked"), ("expired", "expired")],
        method="filter_status",
    )

    class Meta:
        model = Invitation
        fields = ("status",)

    def filter_status(self, queryset, name, value):
        from django.utils import timezone

        now = timezone.now()
        open_ = Q(accepted_at__isnull=True, revoked_at__isnull=True)
        return {
            "pending": queryset.filter(open_, expires_at__gt=now),
            "accepted": queryset.filter(accepted_at__isnull=False),
            "revoked": queryset.filter(revoked_at__isnull=False),
            "expired": queryset.filter(open_, expires_at__lte=now),
        }[value]


@extend_schema(tags=["organization"])
class InvitationViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    permission_classes = [HasPermission("invitations.manage")]
    serializer_class = InvitationSerializer
    filterset_class = InvitationFilter
    search_fields = ("email",)

    def get_queryset(self):
        return Invitation.objects.filter(organization=self.request.organization).select_related("role", "invited_by")

    @extend_schema(request=InvitationCreateSerializer, responses={201: InvitationSerializer})
    def create(self, request):
        s = InvitationCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        invitation = services.create_invitation(
            actor=request.membership,
            email=s.validated_data["email"],
            role_code=s.validated_data["role"],
            request=request,
        )
        return Response(InvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={204: None})
    def destroy(self, request, pk=None):
        services.revoke_invitation(invitation=self.get_object(), request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses=InvitationSerializer)
    @action(detail=True, methods=["post"])
    def resend(self, request, pk=None):
        invitation = services.resend_invitation(invitation=self.get_object(), request=request)
        return Response(InvitationSerializer(invitation).data)


class AuditLogFilter(filters.FilterSet):
    action = filters.CharFilter(lookup_expr="startswith")
    actor = filters.UUIDFilter(field_name="actor__id")
    created_after = filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_before = filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = AuditLog
        fields = ("action", "actor", "target_type", "target_id")


@extend_schema(tags=["organization"])
class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [HasPermission("audit.view")]
    serializer_class = AuditLogSerializer
    filterset_class = AuditLogFilter
    ordering_fields = ("created_at",)

    def get_queryset(self):
        return AuditLog.objects.filter(organization=self.request.organization).select_related("actor")
