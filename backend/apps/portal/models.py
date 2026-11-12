from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel


class CustomerFeedback(BaseModel):
    """A customer's rating of a resolved ticket or a completed work order (once per person)."""

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="feedback")
    ticket = models.ForeignKey(
        "tickets.Ticket", null=True, blank=True, on_delete=models.CASCADE, related_name="feedback"
    )
    work_order = models.ForeignKey(
        "field_service.WorkOrder", null=True, blank=True, on_delete=models.CASCADE, related_name="feedback"
    )
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(blank=True, max_length=2000)

    class Meta:
        ordering = ("-created_at",)
        verbose_name_plural = "customer feedback"
        constraints = [
            models.CheckConstraint(condition=Q(rating__gte=1, rating__lte=5), name="feedback_rating_1_to_5"),
            models.CheckConstraint(
                condition=(Q(ticket__isnull=False) & Q(work_order__isnull=True))
                | (Q(ticket__isnull=True) & Q(work_order__isnull=False)),
                name="feedback_one_subject",
            ),
            models.UniqueConstraint(
                fields=("ticket", "submitted_by"), condition=Q(ticket__isnull=False), name="feedback_once_per_ticket"
            ),
            models.UniqueConstraint(
                fields=("work_order", "submitted_by"),
                condition=Q(work_order__isnull=False),
                name="feedback_once_per_work_order",
            ),
        ]
        indexes = [models.Index(fields=("organization", "created_at"), name="feedback_org_recent")]

    def __str__(self) -> str:
        return f"{self.rating}★"
