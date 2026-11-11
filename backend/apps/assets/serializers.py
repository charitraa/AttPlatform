from rest_framework import serializers

from apps.core.fields import OrgScopedPrimaryKeyRelatedField
from apps.customers.models import Customer

from .models import Asset, AssetCategory


class AssetCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetCategory
        fields = ("id", "name")


class AssetSerializer(serializers.ModelSerializer):
    customer = OrgScopedPrimaryKeyRelatedField(queryset=Customer.objects.filter(archived_at__isnull=True))
    category = OrgScopedPrimaryKeyRelatedField(queryset=AssetCategory.objects.all(), required=False, allow_null=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True, default=None)
    under_warranty = serializers.BooleanField(read_only=True)
    open_ticket_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Asset
        fields = (
            "id",
            "asset_tag",
            "name",
            "customer",
            "customer_name",
            "category",
            "category_name",
            "manufacturer",
            "model",
            "serial_number",
            "location",
            "installed_at",
            "warranty_expires_at",
            "under_warranty",
            "status",
            "purchase_cost",
            "currency",
            "notes",
            "open_ticket_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_asset_tag(self, value: str) -> str:
        value = value.strip().upper()
        qs = Asset.objects.filter(organization=self.context["request"].organization, asset_tag__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("An asset with this tag already exists.")
        return value

    def validate_currency(self, value: str) -> str:
        if value and (len(value) != 3 or not value.isalpha()):
            raise serializers.ValidationError("Use a three-letter currency code, e.g. NPR.")
        return value.upper()

    def validate(self, attrs):
        installed = attrs.get("installed_at", getattr(self.instance, "installed_at", None))
        warranty = attrs.get("warranty_expires_at", getattr(self.instance, "warranty_expires_at", None))
        if installed and warranty and warranty < installed:
            raise serializers.ValidationError({"warranty_expires_at": ["Warranty cannot end before installation."]})
        if attrs.get("purchase_cost") is not None and not attrs.get("currency", getattr(self.instance, "currency", "")):
            raise serializers.ValidationError({"currency": ["Set the currency for the purchase cost."]})
        return attrs
