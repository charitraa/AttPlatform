import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel


class Priority(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


PRIORITY_RANK = {Priority.LOW: 1, Priority.MEDIUM: 2, Priority.HIGH: 3, Priority.CRITICAL: 4}


class TicketStatus(models.TextChoices):
    NEW = "new", "New"
    OPEN = "open", "Open"
    ASSIGNED = "assigned", "Assigned"
    IN_PROGRESS = "in_progress", "In progress"
    PENDING_CUSTOMER = "pending_customer", "Pending customer"
    PENDING_PARTS = "pending_parts", "Pending parts"
    ESCALATED = "escalated", "Escalated"
    RESOLVED = "resolved", "Resolved"
    CLOSED = "closed", "Closed"
    REOPENED = "reopened", "Reopened"


# Statuses where work is still outstanding (used by "open" filters, overdue, KPIs).
ACTIVE_STATUSES = frozenset(TicketStatus) - {TicketStatus.RESOLVED, TicketStatus.CLOSED}


class TicketCategory(BaseModel):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=100)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    department = models.CharField(max_length=100, blank=True)
    description = models.CharField(max_length=255, blank=True)
    default_priority = models.CharField(max_length=16, choices=Priority.choices, default=Priority.MEDIUM)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "ticket categories"
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "parent", "name"), name="uniq_ticket_category", nulls_distinct=False
            ),
        ]

    def __str__(self) -> str:
        return f"{self.parent.name} › {self.name}" if self.parent_id else self.name


class Ticket(BaseModel):
    class Channel(models.TextChoices):
        PORTAL = "portal", "Customer portal"
        EMAIL = "email", "Email"
        PHONE = "phone", "Phone"
        WHATSAPP = "whatsapp", "WhatsApp"
        API = "api", "API"
        STAFF = "staff", "Staff"

    class PrioritySource(models.TextChoices):
        MANUAL = "manual", "Manual"
        AI = "ai", "AI"
        POLICY = "policy", "Category default"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="tickets")
    number = models.PositiveIntegerField(editable=False)
    title = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=TicketStatus.choices, default=TicketStatus.NEW)
    priority = models.CharField(max_length=16, choices=Priority.choices, default=Priority.MEDIUM)
    priority_source = models.CharField(max_length=16, choices=PrioritySource.choices, default=PrioritySource.MANUAL)
    category = models.ForeignKey(
        TicketCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets"
    )
    channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.STAFF)
    tags = ArrayField(models.CharField(max_length=40), default=list, blank=True)

    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="tickets")
    contact = models.ForeignKey(
        "customers.CustomerContact", null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets"
    )
    asset = models.ForeignKey("assets.Asset", null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets")

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    assigned_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="agent_tickets"
    )
    assigned_technician = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="technician_tickets"
    )

    # Denormalised lifecycle timestamps for fast filtering and analytics.
    due_at = models.DateTimeField(null=True, blank=True, help_text="Resolution deadline (set by SLA in Phase 6)")
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)
    customer_confirmed_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("organization", "number"), name="uniq_ticket_number"),
        ]
        indexes = [
            models.Index(fields=("organization", "status")),
            models.Index(fields=("organization", "priority")),
            models.Index(fields=("organization", "assigned_agent", "status")),
            models.Index(fields=("organization", "created_at")),
            models.Index(fields=("organization", "customer")),
            models.Index(
                fields=("organization", "due_at"),
                name="ticket_open_due_idx",
                condition=~Q(status__in=["resolved", "closed"]),
            ),
            GinIndex(SearchVector("title", "description", config="english"), name="ticket_search_idx"),
            GinIndex(fields=("tags",), name="ticket_tags_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.reference} {self.title}"

    @property
    def reference(self) -> str:
        return f"TCK-{self.number:06d}"


class TicketComment(BaseModel):
    """Public replies and internal notes. Internal notes are never shown to customers."""

    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public reply"
        INTERNAL = "internal", "Internal note"

    class Source(models.TextChoices):
        STAFF = "staff", "Staff"
        CUSTOMER = "customer", "Customer"
        SYSTEM = "system", "System"
        AI_SUGGESTION = "ai_suggestion", "AI suggestion (accepted)"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    body = models.TextField()
    visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.PUBLIC)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.STAFF)

    class Meta:
        ordering = ("created_at",)
        indexes = [models.Index(fields=("ticket", "visibility", "created_at"))]

    def __str__(self) -> str:
        return f"{self.get_visibility_display()} on {self.ticket_id}"


def attachment_upload_to(instance: "TicketAttachment", filename: str) -> str:
    # Random storage name: user-supplied filenames never reach the filesystem.
    ext = Path(filename).suffix.lower()[:10]
    return f"attachments/{instance.ticket.organization_id}/{instance.ticket_id}/{uuid.uuid4().hex}{ext}"


class TicketAttachment(BaseModel):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    comment = models.ForeignKey(
        TicketComment, null=True, blank=True, on_delete=models.SET_NULL, related_name="attachments"
    )
    file = models.FileField(upload_to=attachment_upload_to, max_length=255)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    visibility = models.CharField(
        max_length=10, choices=TicketComment.Visibility.choices, default=TicketComment.Visibility.PUBLIC
    )
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ("created_at",)

    def __str__(self) -> str:
        return self.original_name


class TicketHistory(models.Model):
    """Append-only field-level change log; drives the ticket timeline."""

    class ActorType(models.TextChoices):
        USER = "user", "User"
        SYSTEM = "system", "System"
        AI = "ai", "AI"

    id = models.BigAutoField(primary_key=True)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="history")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor_type = models.CharField(max_length=10, choices=ActorType.choices, default=ActorType.USER)
    event = models.CharField(max_length=32)  # created, field_changed, commented, attachment_added, assigned, ...
    field = models.CharField(max_length=64, blank=True)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    internal = models.BooleanField(default=False, help_text="Hidden from customers")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("created_at", "id")
        verbose_name_plural = "ticket history"

    def __str__(self) -> str:
        return f"{self.ticket_id} {self.event} {self.field}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Ticket history is append-only.")
        super().save(*args, **kwargs)


class TicketAssignment(models.Model):
    """Assignment history (who held the ticket, when, and why)."""

    class Role(models.TextChoices):
        AGENT = "agent", "Agent"
        TECHNICIAN = "technician", "Technician"

    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        AI_AUTO = "ai_auto", "AI (automatic)"
        AI_ACCEPTED = "ai_accepted", "AI recommendation accepted"

    id = models.BigAutoField(primary_key=True)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="assignments")
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    role = models.CharField(max_length=12, choices=Role.choices)
    source = models.CharField(max_length=12, choices=Source.choices, default=Source.MANUAL)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    assigned_at = models.DateTimeField(auto_now_add=True)
    unassigned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-assigned_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("ticket", "role"),
                condition=Q(unassigned_at__isnull=True),
                name="one_current_assignment_per_role",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.ticket_id} → {self.assignee_id} ({self.role})"
