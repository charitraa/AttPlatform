from rest_framework import serializers

from .models import AIAnalysis, AIInsight, AIRecommendation, Capability


class AnalysisSerializer(serializers.ModelSerializer):
    ticket = serializers.UUIDField(source="ticket_id", read_only=True, allow_null=True)
    confidence = serializers.FloatField(allow_null=True, read_only=True)

    class Meta:
        model = AIAnalysis
        fields = (
            "id",
            "ticket",
            "kind",
            "status",
            "provider",
            "model",
            "prompt_version",
            "is_mock",
            "input",
            "output",
            "confidence",
            "reasoning",
            "error",
            "latency_ms",
            "tokens_in",
            "tokens_out",
            "attempts",
            "trigger",
            "created_at",
            "completed_at",
        )


class RecommendationSerializer(serializers.ModelSerializer):
    confidence = serializers.FloatField(allow_null=True, read_only=True)
    ticket = serializers.SerializerMethodField()
    decided_by = serializers.SerializerMethodField()
    is_mock = serializers.BooleanField(source="analysis.is_mock", read_only=True)

    class Meta:
        model = AIRecommendation
        fields = (
            "id",
            "type",
            "value",
            "previous_value",
            "confidence",
            "reasoning",
            "status",
            "is_mock",
            "ticket",
            "decided_by",
            "decided_at",
            "override_value",
            "note",
            "created_at",
        )

    def get_ticket(self, obj) -> dict:
        return {"id": str(obj.ticket_id), "reference": obj.ticket.reference, "title": obj.ticket.title}

    def get_decided_by(self, obj) -> str | None:
        return obj.decided_by.full_name if obj.decided_by else None


class DecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["accept", "reject", "override"])
    value = serializers.DictField(required=False)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")


class TicketAIRequestSerializer(serializers.Serializer):
    kinds = serializers.ListField(
        child=serializers.ChoiceField(
            choices=[
                Capability.CLASSIFICATION,
                Capability.PRIORITY,
                Capability.ROUTING,
                Capability.SUMMARY,
                Capability.RESPONSE_SUGGESTION,
            ]
        ),
        min_length=1,
        max_length=5,
    )


class QuestionSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=1000)


class InsightRequestSerializer(serializers.Serializer):
    days = serializers.IntegerField(min_value=7, max_value=180, default=30)


class InsightSerializer(serializers.ModelSerializer):
    is_mock = serializers.BooleanField(source="analysis.is_mock", read_only=True)

    class Meta:
        model = AIInsight
        fields = (
            "id",
            "type",
            "title",
            "body",
            "evidence",
            "period_start",
            "period_end",
            "is_dismissed",
            "is_mock",
            "created_at",
        )
