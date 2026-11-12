from django.urls import reverse
from django.utils import timezone
from rest_framework import serializers

from apps.assets.models import Asset
from apps.core.fields import OrgScopedPrimaryKeyRelatedField
from apps.customers.models import Customer, CustomerContact

from .lifecycle import allowed_transitions
from .models import ACTIVE_STATUSES, Priority, Ticket, TicketAttachment, TicketCategory, TicketComment, TicketHistory
from .selectors import can_see_internal, is_staff_actor


class UserRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    full_name = serializers.CharField()
    email = serializers.EmailField()


def user_ref(user) -> dict | None:
    return {"id": str(user.id), "full_name": user.full_name, "email": user.email} if user else None


class TicketCategorySerializer(serializers.ModelSerializer):
    parent = OrgScopedPrimaryKeyRelatedField(queryset=TicketCategory.objects.all(), required=False, allow_null=True)
    full_name = serializers.CharField(source="__str__", read_only=True)

    class Meta:
        model = TicketCategory
        fields = ("id", "name", "full_name", "parent", "department", "description", "default_priority", "is_active")
        read_only_fields = ("id",)

    def validate(self, attrs):
        org = self.context["request"].organization
        name = attrs.get("name", getattr(self.instance, "name", ""))
        parent = attrs.get("parent", getattr(self.instance, "parent", None))
        qs = TicketCategory.objects.filter(organization=org, parent=parent, name__iexact=name)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
            if parent and parent.pk == self.instance.pk:
                raise serializers.ValidationError({"parent": ["A category cannot be its own parent."]})
        if qs.exists():
            raise serializers.ValidationError({"name": ["A category with this name already exists here."]})
        return attrs


class _NamedRef(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class TicketListSerializer(serializers.ModelSerializer):
    reference = serializers.CharField(read_only=True)
    category = serializers.SerializerMethodField()
    customer = serializers.SerializerMethodField()
    assigned_agent = serializers.SerializerMethodField()
    assigned_technician = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    sla = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = (
            "id",
            "number",
            "reference",
            "title",
            "status",
            "priority",
            "priority_source",
            "channel",
            "tags",
            "category",
            "customer",
            "assigned_agent",
            "assigned_technician",
            "due_at",
            "is_overdue",
            "sla",
            "created_at",
            "updated_at",
            "archived_at",
        )

    def get_category(self, obj) -> dict | None:
        return {"id": str(obj.category_id), "name": str(obj.category)} if obj.category_id else None

    def get_customer(self, obj) -> dict:
        return {"id": str(obj.customer_id), "name": obj.customer.name}

    def get_assigned_agent(self, obj) -> dict | None:
        return user_ref(obj.assigned_agent)

    def get_assigned_technician(self, obj) -> dict | None:
        return user_ref(obj.assigned_technician)

    def get_is_overdue(self, obj) -> bool:
        return bool(obj.due_at and obj.status in ACTIVE_STATUSES and obj.due_at < timezone.now())

    def get_sla(self, obj) -> dict | None:
        """Compact SLA state, for people with sla.view (`null` otherwise or when no policy applies)."""
        request = self.context.get("request")
        tenant = getattr(request, "tenant", None)
        if tenant is None or "sla.view" not in tenant.permissions:
            return None
        from apps.sla.serializers import SLASummarySerializer

        sla = getattr(obj, "sla", None)  # RelatedObjectDoesNotExist is an AttributeError
        return SLASummarySerializer(sla).data if sla else None


class TicketDetailSerializer(TicketListSerializer):
    contact = serializers.SerializerMethodField()
    asset = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    allowed_transitions = serializers.SerializerMethodField()
    capabilities = serializers.SerializerMethodField()

    class Meta(TicketListSerializer.Meta):
        fields = (
            *TicketListSerializer.Meta.fields,
            "description",
            "contact",
            "asset",
            "created_by",
            "first_response_at",
            "resolved_at",
            "closed_at",
            "resolution_notes",
            "customer_confirmed_at",
            "allowed_transitions",
            "capabilities",
        )

    def get_contact(self, obj) -> dict | None:
        c = obj.contact
        return {"id": str(c.id), "name": c.name, "email": c.email, "phone": c.phone} if c else None

    def get_asset(self, obj) -> dict | None:
        a = obj.asset
        return (
            {"id": str(a.id), "asset_tag": a.asset_tag, "name": a.name, "under_warranty": a.under_warranty}
            if a
            else None
        )

    def get_created_by(self, obj) -> dict | None:
        return user_ref(obj.created_by)

    def get_allowed_transitions(self, obj) -> list[str]:
        tenant = self.context["request"].tenant
        if obj.archived_at:
            return []
        staff = is_staff_actor(tenant)
        if staff and "tickets.update" not in tenant.permissions:
            return []
        return allowed_transitions(obj.status, is_staff=staff)

    def get_capabilities(self, obj) -> dict:
        """What the caller may do here; the UI uses this, the API enforces it independently."""
        tenant = self.context["request"].tenant
        perms, staff = tenant.permissions, is_staff_actor(tenant)
        return {
            "edit": staff and "tickets.update" in perms and not obj.archived_at,
            "assign": "tickets.assign" in perms and not obj.archived_at and obj.status != "closed",
            "archive": "tickets.archive" in perms,
            "internal_notes": can_see_internal(tenant),
            "comment": not obj.archived_at and (staff or obj.status != "closed"),
        }


class TicketCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(max_length=20000)
    # Optional for customer-portal users (resolved from their contact); required for staff.
    customer = OrgScopedPrimaryKeyRelatedField(
        queryset=Customer.objects.filter(archived_at__isnull=True), required=False
    )
    contact = OrgScopedPrimaryKeyRelatedField(
        queryset=CustomerContact.objects.all(), org_path="customer__organization", required=False, allow_null=True
    )
    asset = OrgScopedPrimaryKeyRelatedField(queryset=Asset.objects.all(), required=False, allow_null=True)
    category = OrgScopedPrimaryKeyRelatedField(
        queryset=TicketCategory.objects.filter(is_active=True), required=False, allow_null=True
    )
    priority = serializers.ChoiceField(choices=Priority.choices, required=False)
    channel = serializers.ChoiceField(choices=Ticket.Channel.choices, required=False)
    tags = serializers.ListField(child=serializers.CharField(max_length=40), required=False, max_length=20)


class TicketUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(max_length=20000, required=False)
    priority = serializers.ChoiceField(choices=Priority.choices, required=False)
    category = OrgScopedPrimaryKeyRelatedField(
        queryset=TicketCategory.objects.filter(is_active=True), required=False, allow_null=True
    )
    contact = OrgScopedPrimaryKeyRelatedField(
        queryset=CustomerContact.objects.all(), org_path="customer__organization", required=False, allow_null=True
    )
    asset = OrgScopedPrimaryKeyRelatedField(queryset=Asset.objects.all(), required=False, allow_null=True)
    tags = serializers.ListField(child=serializers.CharField(max_length=40), required=False, max_length=20)


class TransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Ticket._meta.get_field("status").choices)
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=5000)
    resolution_notes = serializers.CharField(required=False, allow_blank=True, max_length=10000)


class AssignSerializer(serializers.Serializer):
    """Omit a field to leave it unchanged; send null to unassign."""

    agent = serializers.UUIDField(required=False, allow_null=True)
    technician = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide `agent` and/or `technician`.")
        return attrs


class EscalateSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=2000)


class AttachmentSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = TicketAttachment
        fields = (
            "id",
            "original_name",
            "content_type",
            "size_bytes",
            "sha256",
            "visibility",
            "uploaded_by",
            "comment",
            "created_at",
            "download_url",
        )

    def get_uploaded_by(self, obj) -> dict | None:
        return user_ref(obj.uploaded_by)

    def get_download_url(self, obj) -> str:
        return reverse("ticket-attachment-download", args=[obj.ticket_id, obj.id])


class AttachmentUploadSerializer(serializers.Serializer):
    file = serializers.FileField(allow_empty_file=False)
    visibility = serializers.ChoiceField(choices=TicketComment.Visibility.choices, default="public")


class CommentSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    attachments = AttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = TicketComment
        fields = ("id", "author", "body", "visibility", "source", "attachments", "created_at")

    def get_author(self, obj) -> dict | None:
        return user_ref(obj.author)


class CommentCreateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=20000)
    visibility = serializers.ChoiceField(choices=TicketComment.Visibility.choices, default="public")


class HistorySerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()

    class Meta:
        model = TicketHistory
        fields = ("id", "event", "field", "old_value", "new_value", "actor", "actor_type", "internal", "created_at")

    def get_actor(self, obj) -> dict | None:
        return user_ref(obj.actor)
