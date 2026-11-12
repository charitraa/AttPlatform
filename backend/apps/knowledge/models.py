from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from django.db import models

from apps.core.models import BaseModel


class KnowledgeArticle(BaseModel):
    """
    Review workflow: draft → in_review → published (→ archived). Articles extracted
    by AI from resolved tickets start as drafts and are never published without a
    person approving them. Only published articles feed AI answers.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        IN_REVIEW = "in_review", "In review"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    class Source(models.TextChoices):
        MANUAL = "manual", "Written by staff"
        AI_EXTRACTED = "ai_extracted", "Extracted by AI"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    title = models.CharField(max_length=200)
    summary = models.CharField(max_length=500, blank=True)
    body = models.TextField()
    category = models.ForeignKey(
        "tickets.TicketCategory", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    tags = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.MANUAL)
    source_ticket = models.ForeignKey(
        "tickets.Ticket", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    source_analysis = models.ForeignKey(
        "ai.AIAnalysis", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    published_at = models.DateTimeField(null=True, blank=True)
    helpful_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("-updated_at",)
        indexes = [
            models.Index(fields=("organization", "status")),
            GinIndex(SearchVector("title", "summary", "body", config="english"), name="kb_search_idx"),
        ]

    def __str__(self) -> str:
        return self.title
