import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import ArrayField, DateTimeRangeField, RangeOperators
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Func, Q

from apps.core.models import BaseModel


class Skill(BaseModel):
    """A capability technicians hold; `categories` links skills to the ticket categories that need them."""

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=100, blank=True, help_text="Grouping, e.g. Electrical")
    ticket_categories = models.ManyToManyField("tickets.TicketCategory", blank=True, related_name="required_skills")

    class Meta:
        ordering = ("name",)
        constraints = [models.UniqueConstraint(fields=("organization", "name"), name="uniq_skill")]

    def __str__(self) -> str:
        return self.name


class ServiceArea(BaseModel):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    cities = ArrayField(models.CharField(max_length=100), default=list, blank=True)

    class Meta:
        ordering = ("name",)
        constraints = [models.UniqueConstraint(fields=("organization", "name"), name="uniq_service_area")]

    def __str__(self) -> str:
        return self.name


class Technician(BaseModel):
    """Field-service profile for a user holding the Field Technician role."""

    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        BUSY = "busy", "On a job"
        OFF_DUTY = "off_duty", "Off duty"
        ON_LEAVE = "on_leave", "On leave"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="technician_profiles")
    employee_id = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.AVAILABLE)
    home_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    home_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    max_daily_jobs = models.PositiveSmallIntegerField(
        default=5, validators=[MinValueValidator(1), MaxValueValidator(30)]
    )
    hourly_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    # Location is only recorded when the technician opts in AND is on an active job.
    location_sharing_enabled = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    service_areas = models.ManyToManyField(ServiceArea, blank=True, related_name="technicians")

    class Meta:
        ordering = ("user__first_name", "user__last_name")
        constraints = [
            models.UniqueConstraint(fields=("organization", "user"), name="uniq_technician_user"),
            models.CheckConstraint(
                condition=Q(hourly_cost__gte=0) | Q(hourly_cost__isnull=True), name="technician_cost_non_negative"
            ),
        ]

    def __str__(self) -> str:
        return self.user.full_name


class TechnicianSkill(models.Model):
    technician = models.ForeignKey(Technician, on_delete=models.CASCADE, related_name="skills")
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="holders")
    level = models.PositiveSmallIntegerField(default=3, validators=[MinValueValidator(1), MaxValueValidator(5)])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("technician", "skill"), name="uniq_technician_skill"),
            models.CheckConstraint(condition=Q(level__gte=1, level__lte=5), name="skill_level_1_to_5"),
        ]

    def __str__(self) -> str:
        return f"{self.skill} ({self.level})"


class TechnicianCertification(BaseModel):
    technician = models.ForeignKey(Technician, on_delete=models.CASCADE, related_name="certifications")
    name = models.CharField(max_length=150)
    issuer = models.CharField(max_length=150, blank=True)
    number = models.CharField(max_length=80, blank=True)
    issued_at = models.DateField(null=True, blank=True)
    expires_at = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ("expires_at", "name")

    def __str__(self) -> str:
        return self.name


class TsTzRange(Func):
    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


class TechnicianAvailability(BaseModel):
    """Working shifts and time off. Time off blocks scheduling; shifts are advisory."""

    class Type(models.TextChoices):
        SHIFT = "shift", "Shift"
        TIME_OFF = "time_off", "Time off"

    technician = models.ForeignKey(Technician, on_delete=models.CASCADE, related_name="availability")
    type = models.CharField(max_length=10, choices=Type.choices)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ("starts_at",)
        indexes = [models.Index(fields=("technician", "starts_at"))]
        constraints = [
            models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="availability_ends_after_start")
        ]

    def __str__(self) -> str:
        return f"{self.get_type_display()} {self.starts_at:%Y-%m-%d %H:%M}"


class TechnicianLocation(models.Model):
    """Opt-in location pings, recorded only during active jobs and purged after the retention period."""

    id = models.BigAutoField(primary_key=True)
    technician = models.ForeignKey(Technician, on_delete=models.CASCADE, related_name="locations")
    work_order = models.ForeignKey("WorkOrder", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lng = models.DecimalField(max_digits=9, decimal_places=6)
    accuracy_m = models.PositiveIntegerField(null=True, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-recorded_at",)

    def __str__(self) -> str:
        return f"{self.technician_id} @ {self.recorded_at:%H:%M}"


class WorkOrderStatus(models.TextChoices):
    CREATED = "created", "Created"
    ASSIGNED = "assigned", "Assigned"
    ACCEPTED = "accepted", "Accepted"
    EN_ROUTE = "en_route", "En route"
    ON_SITE = "on_site", "On site"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


ACTIVE_WORK_ORDER_STATUSES = frozenset(
    {
        WorkOrderStatus.ASSIGNED,
        WorkOrderStatus.ACCEPTED,
        WorkOrderStatus.EN_ROUTE,
        WorkOrderStatus.ON_SITE,
        WorkOrderStatus.IN_PROGRESS,
    }
)
FIELD_ACTIVE_STATUSES = frozenset({WorkOrderStatus.EN_ROUTE, WorkOrderStatus.ON_SITE, WorkOrderStatus.IN_PROGRESS})


class WorkOrder(BaseModel):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="work_orders")
    number = models.PositiveIntegerField(editable=False)
    ticket = models.ForeignKey(
        "tickets.Ticket", null=True, blank=True, on_delete=models.SET_NULL, related_name="work_orders"
    )
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="work_orders")
    asset = models.ForeignKey(
        "assets.Asset", null=True, blank=True, on_delete=models.SET_NULL, related_name="work_orders"
    )
    technician = models.ForeignKey(
        Technician, null=True, blank=True, on_delete=models.SET_NULL, related_name="work_orders"
    )
    status = models.CharField(max_length=12, choices=WorkOrderStatus.choices, default=WorkOrderStatus.CREATED)
    priority = models.CharField(max_length=16, default="medium")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    service_address = models.CharField(max_length=300, blank=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    scheduled_start = models.DateTimeField(null=True, blank=True)
    scheduled_end = models.DateTimeField(null=True, blank=True)
    actual_start = models.DateTimeField(null=True, blank=True)
    actual_end = models.DateTimeField(null=True, blank=True)
    service_notes = models.TextField(blank=True)
    completion_summary = models.TextField(blank=True)
    parts_used = models.JSONField(default=list, blank=True)  # [{"name": ..., "quantity": ..., "unit_cost": "..."}]
    labor_minutes = models.PositiveIntegerField(null=True, blank=True)
    labor_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    parts_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    customer_signed_by = models.CharField(max_length=150, blank=True)
    customer_confirmed_at = models.DateTimeField(null=True, blank=True)
    customer_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    customer_comment = models.TextField(blank=True)
    cancelled_reason = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("organization", "number"), name="uniq_work_order_number"),
            models.CheckConstraint(
                condition=Q(scheduled_end__gt=F("scheduled_start"))
                | Q(scheduled_end__isnull=True)
                | Q(scheduled_start__isnull=True),
                name="work_order_schedule_order",
            ),
            models.CheckConstraint(
                condition=Q(customer_rating__gte=1, customer_rating__lte=5) | Q(customer_rating__isnull=True),
                name="work_order_rating_1_to_5",
            ),
        ]
        indexes = [
            models.Index(fields=("organization", "status")),
            models.Index(fields=("organization", "technician", "status")),
            models.Index(fields=("organization", "scheduled_start")),
        ]

    def __str__(self) -> str:
        return f"{self.reference} {self.title}"

    @property
    def reference(self) -> str:
        return f"WO-{self.number:06d}"


class WorkOrderStatusLog(models.Model):
    """Append-only status trail, including where the technician was (if shared)."""

    id = models.BigAutoField(primary_key=True)
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="status_log")
    from_status = models.CharField(max_length=12, blank=True)
    to_status = models.CharField(max_length=12)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    note = models.CharField(max_length=1000, blank=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")

    def __str__(self) -> str:
        return f"{self.work_order_id}: {self.from_status} → {self.to_status}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Work order status log is append-only.")
        super().save(*args, **kwargs)


def evidence_upload_to(instance: "WorkOrderEvidence", filename: str) -> str:
    ext = Path(filename).suffix.lower()[:10]
    return f"evidence/{instance.work_order.organization_id}/{instance.work_order_id}/{uuid.uuid4().hex}{ext}"


class WorkOrderEvidence(BaseModel):
    class Kind(models.TextChoices):
        BEFORE_PHOTO = "before_photo", "Before photo"
        AFTER_PHOTO = "after_photo", "After photo"
        DOCUMENT = "document", "Document"
        SIGNATURE = "signature", "Customer signature"
        OTHER = "other", "Other"

    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="evidence")
    kind = models.CharField(max_length=14, choices=Kind.choices)
    file = models.FileField(upload_to=evidence_upload_to, max_length=255)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    caption = models.CharField(max_length=300, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ("created_at",)

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.original_name}"


class Appointment(BaseModel):
    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="appointments")
    technician = models.ForeignKey(Technician, on_delete=models.CASCADE, related_name="appointments")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CONFIRMED)
    notes = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ("starts_at",)
        indexes = [models.Index(fields=("technician", "starts_at"))]
        constraints = [
            models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="appointment_ends_after_start"),
            # The database itself refuses double-booking a technician (btree_gist).
            ExclusionConstraint(
                name="no_overlapping_confirmed_appointments",
                expressions=[
                    (TsTzRange("starts_at", "ends_at"), RangeOperators.OVERLAPS),
                    ("technician", RangeOperators.EQUAL),
                ],
                condition=Q(status="confirmed"),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.work_order} {self.starts_at:%Y-%m-%d %H:%M}"
