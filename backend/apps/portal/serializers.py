"""
Customer-facing shapes. Deliberately narrow: no internal notes, no agent email
addresses, no SLA deadlines, tags, AI data or priority source.
"""

from rest_framework import serializers

from apps.tickets.lifecycle import allowed_transitions
from apps.tickets.models import Ticket, TicketComment, TicketStatus

# What a customer sees: "waiting on you" is the only status they need to act on.
PUBLIC_STATUS = {
    TicketStatus.NEW: "Received",
    TicketStatus.OPEN: "Received",
    TicketStatus.ASSIGNED: "In progress",
    TicketStatus.IN_PROGRESS: "In progress",
    TicketStatus.PENDING_PARTS: "In progress",
    TicketStatus.ESCALATED: "In progress",
    TicketStatus.REOPENED: "In progress",
    TicketStatus.PENDING_CUSTOMER: "Waiting for your reply",
    TicketStatus.RESOLVED: "Resolved",
    TicketStatus.CLOSED: "Closed",
}


class PortalTicketSerializer(serializers.ModelSerializer):
    reference = serializers.CharField(read_only=True)
    status_label = serializers.SerializerMethodField()
    category = serializers.CharField(source="category.name", default=None, read_only=True)
    asset = serializers.SerializerMethodField()
    handled_by = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()
    feedback = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = (
            "id",
            "reference",
            "title",
            "description",
            "status",
            "status_label",
            "priority",
            "category",
            "asset",
            "handled_by",
            "resolution_notes",
            "created_at",
            "updated_at",
            "resolved_at",
            "closed_at",
            "actions",
            "feedback",
        )

    def get_status_label(self, obj) -> str:
        return PUBLIC_STATUS.get(obj.status, obj.get_status_display())

    def get_asset(self, obj) -> dict | None:
        return {"id": str(obj.asset_id), "name": obj.asset.name} if obj.asset_id else None

    def get_handled_by(self, obj) -> str | None:
        """First name only: customers don't get staff contact details."""
        return obj.assigned_agent.first_name or None if obj.assigned_agent_id else None

    def get_actions(self, obj) -> dict:
        moves = set(allowed_transitions(obj.status, is_staff=False)) if not obj.archived_at else set()
        user = self.context["request"].user
        rated = any(f.submitted_by_id == user.id for f in obj.feedback.all())
        return {
            "reply": obj.status != TicketStatus.CLOSED and not obj.archived_at,
            "confirm": TicketStatus.CLOSED in moves,
            "reopen": TicketStatus.REOPENED in moves,
            "rate": obj.status in (TicketStatus.RESOLVED, TicketStatus.CLOSED) and not rated,
        }

    def get_feedback(self, obj) -> dict | None:
        user = self.context["request"].user
        mine = next((f for f in obj.feedback.all() if f.submitted_by_id == user.id), None)
        return {"rating": mine.rating, "comment": mine.comment, "created_at": mine.created_at} if mine else None


class PortalTicketCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(max_length=10000)
    category = serializers.UUIDField(required=False, allow_null=True)
    asset = serializers.UUIDField(required=False, allow_null=True)


class PortalCommentSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    from_support = serializers.SerializerMethodField()

    class Meta:
        model = TicketComment
        fields = ("id", "author", "from_support", "body", "created_at")

    def get_author(self, obj) -> str:
        if obj.author_id is None:
            return "Support"
        return obj.author.first_name if self.get_from_support(obj) else (obj.author.full_name or "You")

    def get_from_support(self, obj) -> bool:
        return obj.source != TicketComment.Source.CUSTOMER


class FeedbackSerializer(serializers.Serializer):
    ticket = serializers.UUIDField(required=False)
    work_order = serializers.UUIDField(required=False)
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if bool(attrs.get("ticket")) == bool(attrs.get("work_order")):
            raise serializers.ValidationError("Rate either a ticket or a work order.")
        return attrs
