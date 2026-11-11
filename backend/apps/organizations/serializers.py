from zoneinfo import available_timezones

from rest_framework import serializers

from apps.audit.models import AuditLog

from .catalog import SYSTEM_ROLES
from .models import Invitation, Membership, Organization, Role


class OrganizationSettingsSerializer(serializers.Serializer):
    """Allow-list of operational settings. Unknown keys are rejected, not stored."""

    routing_policy = serializers.ChoiceField(
        choices=[
            ("manual", "Manual"),
            ("recommend", "AI recommends, human approves"),
            ("auto", "AI assigns automatically"),
        ],
        required=False,
    )
    ai_enabled = serializers.BooleanField(required=False)
    ticket_auto_close_days = serializers.IntegerField(min_value=1, max_value=90, required=False)

    def to_internal_value(self, data):
        if isinstance(data, dict):
            unknown = set(data) - set(self.fields)
            if unknown:
                raise serializers.ValidationError({k: ["Unknown setting."] for k in sorted(unknown)})
        return super().to_internal_value(data)


ORGANIZATION_SETTING_DEFAULTS = {"routing_policy": "recommend", "ai_enabled": True, "ticket_auto_close_days": 7}


class OrganizationSerializer(serializers.ModelSerializer):
    settings = OrganizationSettingsSerializer(required=False)

    class Meta:
        model = Organization
        fields = ("id", "name", "slug", "timezone", "locale", "settings", "created_at")
        read_only_fields = ("id", "slug", "created_at")

    def validate_timezone(self, value):
        if value not in available_timezones():
            raise serializers.ValidationError("Unknown timezone.")
        return value

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["settings"] = {**ORGANIZATION_SETTING_DEFAULTS, **(instance.settings or {})}
        return data


class RoleSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()
    assignable = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = ("code", "name", "description", "rank", "is_system", "permissions", "assignable")

    def get_permissions(self, obj) -> list[str]:
        if obj.code in SYSTEM_ROLES:
            return sorted(SYSTEM_ROLES[obj.code].permissions)
        return sorted(p.code for p in obj.permissions.all())

    def get_assignable(self, obj) -> bool:
        return obj.code in self.context.get("assignable_codes", ())


class _UserSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    full_name = serializers.CharField()
    last_login = serializers.DateTimeField(allow_null=True)


class MemberSerializer(serializers.ModelSerializer):
    """A user as seen within the current organization. `id` is the user's ID."""

    id = serializers.UUIDField(source="user.id", read_only=True)
    user = _UserSummarySerializer(read_only=True)
    role = serializers.SerializerMethodField()
    joined_at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Membership
        fields = ("id", "user", "role", "is_active", "joined_at")

    def get_role(self, obj) -> dict:
        return {"code": obj.role.code, "name": obj.role.name}


class MemberUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=sorted(SYSTEM_ROLES), required=False)
    is_active = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide `role` and/or `is_active`.")
        return attrs


class InvitationSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    status = serializers.CharField(read_only=True)
    invited_by = serializers.SerializerMethodField()

    class Meta:
        model = Invitation
        fields = (
            "id", "email", "role", "status", "expires_at", "accepted_at", "revoked_at", "invited_by", "created_at",
        )

    def get_role(self, obj) -> dict:
        return {"code": obj.role.code, "name": obj.role.name}

    def get_invited_by(self, obj) -> str | None:
        return obj.invited_by.full_name if obj.invited_by else None


class InvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=sorted(SYSTEM_ROLES))


class AuditLogSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = ("id", "action", "actor", "actor_type", "target_type", "target_id", "changes", "ip_address",
                  "request_id", "created_at")

    def get_actor(self, obj) -> dict | None:
        return {"id": str(obj.actor.id), "email": obj.actor.email} if obj.actor else None
