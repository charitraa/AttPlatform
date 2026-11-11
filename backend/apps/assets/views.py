from django.db.models import Count, Q
from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets

from apps.audit import services as audit
from apps.organizations.permissions import MethodPermissions
from apps.tickets.models import ACTIVE_STATUSES

from .models import Asset, AssetCategory
from .serializers import AssetCategorySerializer, AssetSerializer

PERMS = {
    "GET": ["assets.view"],
    "POST": ["assets.manage"],
    "PATCH": ["assets.manage"],
    "PUT": ["assets.manage"],
    "DELETE": ["assets.manage"],
}


class AssetFilter(filters.FilterSet):
    customer = filters.UUIDFilter(field_name="customer_id")
    category = filters.UUIDFilter(field_name="category_id")
    warranty = filters.ChoiceFilter(choices=[("active", "active"), ("expired", "expired")], method="filter_warranty")

    class Meta:
        model = Asset
        fields = ("customer", "category", "status", "warranty")

    def filter_warranty(self, queryset, name, value):
        from django.utils import timezone

        today = timezone.localdate()
        return (
            queryset.filter(warranty_expires_at__gte=today)
            if value == "active"
            else queryset.filter(Q(warranty_expires_at__lt=today) | Q(warranty_expires_at__isnull=True))
        )


@extend_schema(tags=["assets"])
class AssetViewSet(viewsets.ModelViewSet):
    permission_classes = [MethodPermissions]
    method_permissions = PERMS
    serializer_class = AssetSerializer
    filterset_class = AssetFilter
    search_fields = ("asset_tag", "name", "serial_number", "manufacturer", "model", "customer__name")
    ordering_fields = ("name", "asset_tag", "installed_at", "warranty_expires_at", "created_at")
    ordering = ("name",)

    def get_queryset(self):
        return (
            Asset.objects.filter(organization=self.request.organization)
            .select_related("customer", "category")
            .annotate(open_ticket_count=Count("tickets", filter=Q(tickets__status__in=ACTIVE_STATUSES)))
        )

    def perform_create(self, serializer):
        asset = serializer.save(organization=self.request.organization)
        audit.record("asset.created", request=self.request, target=asset)

    def perform_update(self, serializer):
        asset = serializer.save()
        audit.record(
            "asset.updated",
            request=self.request,
            target=asset,
            changes={k: str(v) for k, v in serializer.validated_data.items()},
        )

    def perform_destroy(self, instance):
        # Assets referenced by tickets are kept for history; retire them instead.
        if instance.tickets.exists():
            from apps.core.exceptions import Conflict

            raise Conflict("This asset has tickets. Set its status to Retired instead of deleting it.")
        audit.record("asset.deleted", request=self.request, target=instance, changes={"asset_tag": instance.asset_tag})
        instance.delete()


@extend_schema(tags=["assets"])
class AssetCategoryViewSet(viewsets.ModelViewSet):
    permission_classes = [MethodPermissions]
    method_permissions = PERMS
    serializer_class = AssetCategorySerializer
    pagination_class = None

    def get_queryset(self):
        return AssetCategory.objects.filter(organization=self.request.organization)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.organization)
