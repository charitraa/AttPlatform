from rest_framework import serializers

from .models import Channel, Notification, NotificationType


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ("id", "type", "title", "body", "link", "data", "is_read", "read_at", "created_at")

    def get_is_read(self, obj) -> bool:
        return obj.read_at is not None


class PreferenceSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=NotificationType.choices)
    channel = serializers.ChoiceField(choices=Channel.choices)
    enabled = serializers.BooleanField()


class MarkReadSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.UUIDField(), required=False, allow_empty=False, max_length=500)
