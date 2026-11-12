from rest_framework import serializers

from apps.core.fields import OrgScopedPrimaryKeyRelatedField
from apps.tickets.models import TicketCategory

from .models import KnowledgeArticle


class ArticleSerializer(serializers.ModelSerializer):
    category = OrgScopedPrimaryKeyRelatedField(queryset=TicketCategory.objects.all(), required=False, allow_null=True)
    category_name = serializers.CharField(source="category.name", read_only=True, default=None)
    author = serializers.CharField(source="author.full_name", read_only=True, default=None)
    reviewed_by = serializers.CharField(source="reviewed_by.full_name", read_only=True, default=None)
    source_ticket = serializers.SerializerMethodField()

    class Meta:
        model = KnowledgeArticle
        fields = (
            "id",
            "title",
            "summary",
            "body",
            "category",
            "category_name",
            "tags",
            "status",
            "source",
            "source_ticket",
            "author",
            "reviewed_by",
            "published_at",
            "helpful_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "status", "source", "published_at", "helpful_count", "created_at", "updated_at")

    def get_source_ticket(self, obj) -> dict | None:
        t = obj.source_ticket
        return {"id": str(t.id), "reference": t.reference, "title": t.title} if t else None

    def validate_tags(self, value):
        return sorted({t.strip().lower()[:40] for t in value if t.strip()})[:10]
