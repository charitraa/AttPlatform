from rest_framework import serializers

from .models import Customer, CustomerContact


class CustomerContactSerializer(serializers.ModelSerializer):
    has_portal_access = serializers.SerializerMethodField()

    class Meta:
        model = CustomerContact
        fields = ("id", "name", "email", "phone", "job_title", "is_primary", "has_portal_access", "created_at")
        read_only_fields = ("id", "created_at")

    def get_has_portal_access(self, obj) -> bool:
        return obj.user_id is not None


class CustomerSerializer(serializers.ModelSerializer):
    open_ticket_count = serializers.IntegerField(read_only=True, required=False)
    asset_count = serializers.IntegerField(read_only=True, required=False)
    primary_contact = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = (
            "id",
            "name",
            "type",
            "tier",
            "email",
            "phone",
            "address_line1",
            "address_line2",
            "city",
            "region",
            "postal_code",
            "country",
            "notes",
            "archived_at",
            "created_at",
            "updated_at",
            "open_ticket_count",
            "asset_count",
            "primary_contact",
        )
        read_only_fields = ("id", "archived_at", "created_at", "updated_at")

    def get_primary_contact(self, obj) -> dict | None:
        contact = next((c for c in obj.contacts.all() if c.is_primary), None)
        return {"id": str(contact.id), "name": contact.name, "email": contact.email} if contact else None

    def validate_country(self, value: str) -> str:
        value = value.upper()
        if value and (len(value) != 2 or not value.isalpha()):
            raise serializers.ValidationError("Use a two-letter country code, e.g. NP.")
        return value

    def validate_name(self, value: str) -> str:
        org = self.context["request"].organization
        qs = Customer.objects.filter(organization=org, name__iexact=value.strip(), archived_at__isnull=True)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A customer with this name already exists.")
        return value.strip()
