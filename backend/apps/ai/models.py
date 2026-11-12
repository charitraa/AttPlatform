from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class Capability(models.TextChoices):
    CLASSIFICATION = "classification", "Classification"
    PRIORITY = "priority", "Priority prediction"
    SUMMARY = "summary", "Summary"
    ROUTING = "routing", "Smart routing"
    RESPONSE_SUGGESTION = "response_suggestion", "Response suggestion"
    KNOWLEDGE_ANSWER = "knowledge_answer", "Knowledge assistant"
    INSIGHTS = "insights", "Insights"
    KNOWLEDGE_EXTRACTION = "knowledge_extraction", "Knowledge extraction"


class AIAnalysis(BaseModel):
    """One AI run: inputs fingerprint, raw structured output, and how it went."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    ticket = models.ForeignKey(
        "tickets.Ticket", null=True, blank=True, on_delete=models.CASCADE, related_name="ai_analyses"
    )
    kind = models.CharField(max_length=32, choices=Capability.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    provider = models.CharField(max_length=32, blank=True)
    model = models.CharField(max_length=100, blank=True)
    prompt_version = models.CharField(max_length=40, blank=True)
    input_hash = models.CharField(max_length=64, blank=True, db_index=True)
    input = models.JSONField(default=dict, blank=True, help_text="Request parameters (e.g. the question asked)")
    output = models.JSONField(null=True, blank=True)
    confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    reasoning = models.TextField(blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    tokens_in = models.PositiveIntegerField(null=True, blank=True)
    tokens_out = models.PositiveIntegerField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.CharField(max_length=500, blank=True)
    is_mock = models.BooleanField(default=False)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    trigger = models.CharField(max_length=20, default="manual")  # manual | ticket_created | ticket_closed | schedule
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name_plural = "AI analyses"
        indexes = [
            models.Index(fields=("organization", "kind", "created_at")),
            models.Index(fields=("ticket", "kind", "created_at")),
        ]

    def __str__(self) -> str:
        return f"{self.kind} ({self.status})"


class AIRecommendation(BaseModel):
    """
    An actionable suggestion. AI never silently changes a ticket: a recommendation is
    either applied automatically under an explicit org policy (`auto_applied`) or
    decided by a person (`accepted`, `rejected`, `overridden`).
    """

    class Type(models.TextChoices):
        CATEGORY = "category", "Category"
        PRIORITY = "priority", "Priority"
        ASSIGNEE = "assignee", "Agent"
        TECHNICIAN = "technician", "Technician"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        OVERRIDDEN = "overridden", "Overridden"
        AUTO_APPLIED = "auto_applied", "Applied automatically"
        SUPERSEDED = "superseded", "Superseded"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    analysis = models.ForeignKey(AIAnalysis, on_delete=models.CASCADE, related_name="recommendations")
    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.CASCADE, related_name="ai_recommendations")
    type = models.CharField(max_length=16, choices=Type.choices)
    value = models.JSONField()  # e.g. {"priority": "high"} / {"category_id": "...", "name": "HVAC"}
    previous_value = models.JSONField(null=True, blank=True)
    confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    reasoning = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    override_value = models.JSONField(null=True, blank=True)
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("organization", "status", "type")), models.Index(fields=("ticket", "status"))]

    def __str__(self) -> str:
        return f"{self.type} → {self.value} ({self.status})"


class AIInsight(BaseModel):
    class Type(models.TextChoices):
        RECURRING_ISSUE = "recurring_issue", "Recurring issue"
        PATTERN = "pattern", "Pattern"
        SLA_RISK = "sla_risk", "Deadline risk"
        REPORT = "report", "Report"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    analysis = models.ForeignKey(AIAnalysis, on_delete=models.CASCADE, related_name="insights")
    type = models.CharField(max_length=20, choices=Type.choices)
    title = models.CharField(max_length=200)
    body = models.TextField()
    evidence = models.JSONField(default=list, blank=True)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    is_dismissed = models.BooleanField(default=False)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.title
