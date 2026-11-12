"""
SLA policies and per-ticket SLA clocks.

Design notes
- `SLAInstance` copies the target minutes and warning threshold when it is applied,
  so editing a policy never rewrites the history of tickets already measured.
- Clocks are expressed as working seconds on the policy's business calendar:
  `due = add_business_seconds(started_at, target + paused_seconds)`. Pausing adds
  the working time spent paused, which is why recomputation after a priority change
  or a resume is a pure function of the stored fields.
- The first-response clock never pauses; the resolution clock pauses while the
  ticket waits on the customer or on parts, and between resolve and reopen.
- `warn_at` / `due_at` per metric are materialised so the minute-by-minute monitor
  is a plain indexed range query.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel
from apps.tickets.models import Priority


class BusinessHours(BaseModel):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=100)
    timezone = models.CharField(max_length=64, default="UTC")
    # {"mon": [["09:00", "17:00"]], ...}; validated by business_time.validate_schedule
    schedule = models.JSONField(default=dict)

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "business hours"
        constraints = [models.UniqueConstraint(fields=("organization", "name"), name="uniq_business_hours_name")]

    def __str__(self) -> str:
        return self.name


class Holiday(models.Model):
    business_hours = models.ForeignKey(BusinessHours, on_delete=models.CASCADE, related_name="holidays")
    date = models.DateField()
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ("date",)
        constraints = [models.UniqueConstraint(fields=("business_hours", "date"), name="uniq_holiday_date")]

    def __str__(self) -> str:
        return f"{self.date} {self.name}"


class SLAPolicy(BaseModel):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    is_default = models.BooleanField(default=False, help_text="Used when no other policy matches.")
    is_active = models.BooleanField(default=True)
    business_hours = models.ForeignKey(
        BusinessHours,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="policies",
        help_text="Empty means the clock runs 24/7.",
    )
    # {"categories": [uuid], "customer_tiers": ["gold"], "channels": ["email"]}; empty list = any
    conditions = models.JSONField(default=dict, blank=True)
    priority_order = models.PositiveIntegerField(default=100, help_text="Lower is evaluated first.")
    escalate_on_breach = models.BooleanField(
        default=True, help_text="Move the ticket to Escalated when the resolution target is breached."
    )

    class Meta:
        ordering = ("priority_order", "name")
        verbose_name = "SLA policy"
        verbose_name_plural = "SLA policies"
        constraints = [
            models.UniqueConstraint(fields=("organization", "name"), name="uniq_sla_policy_name"),
            models.UniqueConstraint(
                fields=("organization",), condition=Q(is_default=True), name="one_default_sla_policy"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class SLATarget(models.Model):
    policy = models.ForeignKey(SLAPolicy, on_delete=models.CASCADE, related_name="targets")
    priority = models.CharField(max_length=16, choices=Priority.choices)
    first_response_minutes = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    resolution_minutes = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    warning_threshold_pct = models.PositiveSmallIntegerField(
        default=80, validators=[MinValueValidator(1), MaxValueValidator(99)]
    )

    class Meta:
        ordering = ("policy", "priority")
        constraints = [
            models.UniqueConstraint(fields=("policy", "priority"), name="uniq_sla_target_priority"),
            models.CheckConstraint(
                condition=Q(warning_threshold_pct__gte=1, warning_threshold_pct__lte=99), name="sla_warning_pct_range"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.policy} / {self.priority}"


class MetricStatus(models.TextChoices):
    ON_TRACK = "on_track", "On track"
    WARNING = "warning", "At risk"
    BREACHED = "breached", "Breached"
    MET = "met", "Met"


class SLAInstance(BaseModel):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    ticket = models.OneToOneField("tickets.Ticket", on_delete=models.CASCADE, related_name="sla")
    policy = models.ForeignKey(SLAPolicy, null=True, on_delete=models.SET_NULL, related_name="instances")
    policy_name = models.CharField(max_length=100)  # snapshot
    business_hours = models.ForeignKey(BusinessHours, null=True, blank=True, on_delete=models.SET_NULL)
    priority = models.CharField(max_length=16, choices=Priority.choices)
    response_minutes = models.PositiveIntegerField()
    resolution_minutes = models.PositiveIntegerField()
    warning_threshold_pct = models.PositiveSmallIntegerField()
    started_at = models.DateTimeField()

    response_due_at = models.DateTimeField()
    response_warn_at = models.DateTimeField()
    response_status = models.CharField(max_length=10, choices=MetricStatus.choices, default=MetricStatus.ON_TRACK)
    responded_at = models.DateTimeField(null=True, blank=True)

    resolution_due_at = models.DateTimeField()
    resolution_warn_at = models.DateTimeField()
    resolution_status = models.CharField(max_length=10, choices=MetricStatus.choices, default=MetricStatus.ON_TRACK)
    resolved_at = models.DateTimeField(null=True, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    paused_seconds = models.PositiveIntegerField(default=0, help_text="Working seconds spent paused.")
    escalated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("resolution_due_at",)
        verbose_name = "SLA instance"
        indexes = [
            models.Index(fields=("resolution_status", "resolution_due_at"), name="sla_resolution_monitor"),
            models.Index(fields=("response_status", "response_due_at"), name="sla_response_monitor"),
            models.Index(fields=("organization", "started_at"), name="sla_org_started"),
        ]

    def __str__(self) -> str:
        return f"SLA {self.ticket_id}"

    @property
    def is_paused(self) -> bool:
        return self.paused_at is not None


class SLAEvent(models.Model):
    class Type(models.TextChoices):
        APPLIED = "applied", "Applied"
        RECALCULATED = "recalculated", "Recalculated"
        WARNING = "warning", "Warning"
        BREACHED = "breached", "Breached"
        PAUSED = "paused", "Paused"
        RESUMED = "resumed", "Resumed"
        MET = "met", "Met"
        ESCALATED = "escalated", "Escalated"

    class Metric(models.TextChoices):
        RESPONSE = "response", "First response"
        RESOLUTION = "resolution", "Resolution"

    sla = models.ForeignKey(SLAInstance, on_delete=models.CASCADE, related_name="events")
    type = models.CharField(max_length=14, choices=Type.choices)
    metric = models.CharField(max_length=10, choices=Metric.choices, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)
    payload = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ("occurred_at", "id")
        constraints = [
            # The monitor may run concurrently or twice; a warning/breach is recorded once per metric.
            models.UniqueConstraint(
                fields=("sla", "type", "metric"),
                condition=Q(type__in=["warning", "breached", "escalated"]),
                name="sla_event_once",
            )
        ]

    def __str__(self) -> str:
        return f"{self.type} {self.metric}"
