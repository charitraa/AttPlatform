from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import BaseModel


class AssetCategory(BaseModel):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "asset categories"
        constraints = [models.UniqueConstraint(fields=("organization", "name"), name="uniq_asset_category")]

    def __str__(self) -> str:
        return self.name


class Asset(BaseModel):
    """Equipment installed at a customer and serviced by the organization."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        IN_REPAIR = "in_repair", "In repair"
        RETIRED = "retired", "Retired"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="assets")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="assets")
    category = models.ForeignKey(AssetCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name="assets")
    asset_tag = models.CharField(max_length=64, help_text="Organization-unique identifier, e.g. a label on the device")
    name = models.CharField(max_length=200)
    manufacturer = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    serial_number = models.CharField(max_length=100, blank=True, db_index=True)
    location = models.CharField(max_length=200, blank=True)
    installed_at = models.DateField(null=True, blank=True)
    warranty_expires_at = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    purchase_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("name",)
        indexes = [models.Index(fields=("organization", "customer"))]
        constraints = [
            models.UniqueConstraint(fields=("organization", "asset_tag"), name="uniq_asset_tag"),
            models.CheckConstraint(
                condition=Q(purchase_cost__gte=0) | Q(purchase_cost__isnull=True), name="asset_cost_non_negative"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.asset_tag} · {self.name}"

    @property
    def under_warranty(self) -> bool:
        return bool(self.warranty_expires_at and self.warranty_expires_at >= timezone.localdate())
