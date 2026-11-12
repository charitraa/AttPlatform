from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.audit import services as audit
from apps.core.exceptions import InvalidTransition
from apps.organizations.permissions import MethodPermissions

from .models import KnowledgeArticle
from .serializers import ArticleSerializer

S = KnowledgeArticle.Status
# Review workflow. Publishing requires knowledge.manage (enforced by the POST permission).
TRANSITIONS = {
    "submit": ({S.DRAFT}, S.IN_REVIEW),
    "publish": ({S.DRAFT, S.IN_REVIEW}, S.PUBLISHED),
    "return_to_draft": ({S.IN_REVIEW, S.PUBLISHED}, S.DRAFT),
    "archive": ({S.DRAFT, S.IN_REVIEW, S.PUBLISHED}, S.ARCHIVED),
}


@extend_schema(tags=["knowledge"])
class ArticleViewSet(viewsets.ModelViewSet):
    """
    Readers (knowledge.view) see published articles; editors (knowledge.manage) see
    everything, including AI-extracted drafts awaiting review.
    """

    permission_classes = [MethodPermissions]
    method_permissions = {
        "GET": ["knowledge.view"],
        "POST": ["knowledge.manage"],
        "PATCH": ["knowledge.manage"],
        "PUT": ["knowledge.manage"],
        "DELETE": ["knowledge.manage"],
    }
    serializer_class = ArticleSerializer
    filterset_fields = ("status", "source", "category")
    ordering_fields = ("updated_at", "title", "published_at")

    def get_queryset(self):
        qs = KnowledgeArticle.objects.filter(organization=self.request.organization).select_related(
            "category", "author", "reviewed_by", "source_ticket"
        )
        if "knowledge.manage" not in self.request.tenant.permissions:
            qs = qs.filter(status=S.PUBLISHED)
        term = self.request.query_params.get("search", "").strip()
        if term and self.action == "list":
            vector = SearchVector("title", "summary", "body", config="english")
            query = SearchQuery(term, search_type="websearch", config="english")
            qs = qs.annotate(rank=SearchRank(vector, query)).filter(rank__gt=0).order_by("-rank")
        return qs

    def perform_create(self, serializer):
        article = serializer.save(organization=self.request.organization, author=self.request.user)
        audit.record("knowledge.article_created", request=self.request, target=article)

    def perform_update(self, serializer):
        article = serializer.save()
        audit.record("knowledge.article_updated", request=self.request, target=article)

    def perform_destroy(self, instance):
        audit.record(
            "knowledge.article_deleted", request=self.request, target=instance, changes={"title": instance.title}
        )
        instance.delete()

    def _move(self, request, name):
        article = self.get_object()
        allowed_from, to = TRANSITIONS[name]
        if article.status not in allowed_from:
            raise InvalidTransition(f"Cannot {name.replace('_', ' ')} an article that is {article.status}.")
        old = article.status
        article.status = to
        if to == S.PUBLISHED:
            article.published_at, article.reviewed_by = timezone.now(), request.user
        article.save()
        audit.record(
            "knowledge.article_status_changed",
            request=request,
            target=article,
            changes={"status": {"from": old, "to": to}},
        )
        return Response(ArticleSerializer(article, context=self.get_serializer_context()).data)

    @extend_schema(request=None, responses=ArticleSerializer)
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        return self._move(request, "submit")

    @extend_schema(request=None, responses=ArticleSerializer)
    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        return self._move(request, "publish")

    @extend_schema(request=None, responses=ArticleSerializer)
    @action(detail=True, methods=["post"], url_path="return-to-draft")
    def return_to_draft(self, request, pk=None):
        return self._move(request, "return_to_draft")

    @extend_schema(request=None, responses=ArticleSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        return self._move(request, "archive")
