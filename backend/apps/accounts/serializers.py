from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.organizations.models import Membership
from apps.organizations.tenancy import active_memberships, permissions_for

User = get_user_model()

TIMEZONE_MAX = 64


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)


class RegisterSerializer(serializers.Serializer):
    organization_name = serializers.CharField(max_length=200)
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ResetPasswordSerializer(serializers.Serializer):
    uid = serializers.CharField(max_length=64)
    token = serializers.CharField(max_length=128)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)


class InvitationTokenSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=128)


class AcceptInvitationSerializer(InvitationTokenSerializer):
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)


class InvitationPreviewSerializer(serializers.Serializer):
    organization_name = serializers.CharField()
    email = serializers.EmailField()
    role_name = serializers.CharField()
    existing_account = serializers.BooleanField()


class ProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "phone", "timezone")

    def validate_timezone(self, value: str) -> str:
        from zoneinfo import available_timezones

        if value not in available_timezones():
            raise serializers.ValidationError("Unknown timezone.")
        return value


class _OrgRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()


class _RoleRefSerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()


class MembershipRefSerializer(serializers.Serializer):
    organization = _OrgRefSerializer()
    role = _RoleRefSerializer()


class MeSerializer(serializers.Serializer):
    """The signed-in user plus the active organization context the UI needs."""

    id = serializers.UUIDField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    full_name = serializers.CharField()
    phone = serializers.CharField()
    timezone = serializers.CharField()
    date_joined = serializers.DateTimeField()
    last_login = serializers.DateTimeField(allow_null=True)
    organization = _OrgRefSerializer()
    role = _RoleRefSerializer()
    permissions = serializers.ListField(child=serializers.CharField())
    memberships = MembershipRefSerializer(many=True)


def build_me(user, membership: Membership | None = None) -> dict:
    memberships = list(active_memberships(user))
    membership = membership or (memberships[0] if memberships else None)
    if membership is None:
        raise ValueError("User has no active membership.")
    return MeSerializer(
        {
            **{
                f: getattr(user, f)
                for f in (
                    "id",
                    "email",
                    "first_name",
                    "last_name",
                    "full_name",
                    "phone",
                    "timezone",
                    "date_joined",
                    "last_login",
                )
            },
            "organization": membership.organization,
            "role": membership.role,
            "permissions": sorted(permissions_for(membership)),
            "memberships": memberships,
        }
    ).data
