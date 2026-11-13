from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.organizations.permissions import HasPermission
from apps.tickets.selectors import visible_tickets

from . import services
from .models import AIAnalysis, AIInsight, AIRecommendation
from .serializers import (
    AnalysisSerializer,
    DecisionSerializer,
    InsightRequestSerializer,
    InsightSerializer,
    QuestionSerializer,
    RecommendationSerializer,
    TicketAIRequestSerializer,
)


class AIThrottled(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai"


def _latest_per_kind(qs):
    latest = {}
    for a in qs.order_by("-created_at"):
        latest.setdefault(a.kind, a)
    return list(latest.values())


@extend_schema(tags=["ai"])
class TicketAIView(AIThrottled):
    """GET: latest analysis per capability + recommendations for a ticket. POST: run capabilities (202)."""

    permission_classes = [HasPermission("ai.use")]

    def get_ticket(self, request, ticket_pk):
        return get_object_or_404(visible_tickets(request.tenant), pk=ticket_pk)

    def get_throttles(self):
        return super().get_throttles() if self.request.method == "POST" else []

    @extend_schema(responses=None)
    def get(self, request, ticket_pk):
        ticket = self.get_ticket(request, ticket_pk)
        analyses = _latest_per_kind(AIAnalysis.objects.filter(ticket=ticket))
        recs = AIRecommendation.objects.filter(ticket=ticket).select_related("ticket", "analysis", "decided_by")[:20]
        return Response(
            {
                "analyses": AnalysisSerializer(analyses, many=True).data,
                "recommendations": RecommendationSerializer(recs, many=True).data,
                "ai_enabled": services.ai_enabled(ticket.organization),
            }
        )

    @extend_schema(request=TicketAIRequestSerializer, responses={202: AnalysisSerializer(many=True)})
    def post(self, request, ticket_pk):
        ticket = self.get_ticket(request, ticket_pk)
        s = TicketAIRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        analyses = services.request_ticket_analysis(ticket=ticket, kinds=s.validated_data["kinds"], user=request.user)
        for a in analyses:
            a.refresh_from_db()  # usually still pending: the task runs after commit; clients poll
        return Response(AnalysisSerializer(analyses, many=True).data, status=status.HTTP_202_ACCEPTED)


@extend_schema(tags=["ai"])
class AnalysisViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Poll an analysis started with a 202."""

    permission_classes = [HasPermission("ai.use")]
    serializer_class = AnalysisSerializer

    queryset = AIAnalysis.objects.none()  # for the API schema only; get_queryset() scopes every request

    def get_queryset(self):
        tenant = self.request.tenant
        return AIAnalysis.objects.filter(organization=tenant.organization).filter(
            Q(ticket__isnull=True) | Q(ticket__in=visible_tickets(tenant))
        )


@extend_schema(tags=["ai"])
class RecommendationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [HasPermission("ai.use")]
    serializer_class = RecommendationSerializer
    filterset_fields = ("status", "type", "ticket")

    queryset = AIRecommendation.objects.none()  # for the API schema only; get_queryset() scopes every request

    def get_queryset(self):
        tenant = self.request.tenant
        return AIRecommendation.objects.filter(
            organization=tenant.organization, ticket__in=visible_tickets(tenant)
        ).select_related("ticket", "analysis", "decided_by")

    def get_permissions(self):
        if self.action == "decide":
            return [HasPermission("ai.override")()]
        return super().get_permissions()

    @extend_schema(request=DecisionSerializer, responses=RecommendationSerializer)
    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        s = DecisionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        rec = services.decide(rec=self.get_object(), tenant=request.tenant, request=request, **s.validated_data)
        return Response(RecommendationSerializer(rec).data)


@extend_schema(tags=["ai"])
class AssistantView(AIThrottled):
    permission_classes = [HasPermission("ai.use", "knowledge.view")]

    @extend_schema(responses=AnalysisSerializer(many=True))
    def get(self, request):
        """The caller's recent questions and answers."""
        qs = AIAnalysis.objects.filter(
            organization=request.organization, kind="knowledge_answer", requested_by=request.user
        )[:20]
        return Response(AnalysisSerializer(qs, many=True).data)

    @extend_schema(request=QuestionSerializer, responses={202: AnalysisSerializer})
    def post(self, request):
        s = QuestionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        analysis = services.request_answer(
            organization=request.organization, question=s.validated_data["question"], user=request.user
        )
        analysis.refresh_from_db()
        return Response(AnalysisSerializer(analysis).data, status=status.HTTP_202_ACCEPTED)


@extend_schema(tags=["ai"])
class InsightViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [HasPermission("ai.use", "analytics.view")]
    serializer_class = InsightSerializer
    filterset_fields = ("type", "is_dismissed")

    queryset = AIInsight.objects.none()  # for the API schema only; get_queryset() scopes every request

    def get_queryset(self):
        return AIInsight.objects.filter(organization=self.request.organization).select_related("analysis")

    def get_throttles(self):
        return [ScopedRateThrottle()] if self.action == "generate" else []

    throttle_scope = "ai"

    @extend_schema(request=InsightRequestSerializer, responses={202: AnalysisSerializer})
    @action(detail=False, methods=["post"])
    def generate(self, request):
        s = InsightRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        analysis = services.request_insights(
            organization=request.organization, user=request.user, days=s.validated_data["days"]
        )
        analysis.refresh_from_db()
        return Response(AnalysisSerializer(analysis).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(request=None, responses=InsightSerializer)
    @action(detail=True, methods=["post"])
    def dismiss(self, request, pk=None):
        insight = self.get_object()
        insight.is_dismissed = True
        insight.save(update_fields=["is_dismissed", "updated_at"])
        return Response(InsightSerializer(insight).data)


@extend_schema(tags=["ai"], responses=OpenApiTypes.OBJECT)
class AIStatusView(APIView):
    """Which provider is active (never the key) and how often people accept AI suggestions."""

    permission_classes = [HasPermission("ai.use")]

    def get(self, request):
        org = request.organization
        return Response(
            {
                "provider": settings.AI_PROVIDER,
                "model": settings.AI_MODEL or ("claude-opus-5-5" if settings.AI_PROVIDER == "anthropic" else ""),
                "mock_mode": settings.AI_PROVIDER == "mock",
                "ai_enabled": services.ai_enabled(org),
                "auto_triage": services.org_setting(org, "ai_auto_triage", False),
                "routing_policy": services.org_setting(org, "routing_policy", "recommend"),
                "auto_apply_min_confidence": services.threshold(),
                "acceptance": services.acceptance_stats(org)
                if "analytics.view" in request.tenant.permissions
                else None,
            }
        )
