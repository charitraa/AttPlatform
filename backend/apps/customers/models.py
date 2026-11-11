from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel


class Customer(BaseModel):
    """A customer account (company or individual) served by the organization."""

    class Type(models.TextChoices):
        BUSINESS = "business", "Business"
        INDIVIDUAL = "individual", "Individual"

    class Tier(models.TextChoices):
        STANDARD = "standard", "Standard"
        PREMIUM = "premium", "Premium"
        ENTERPRISE = "enterprise", "Enterprise"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="customers")
    name = models.CharField(max_length=200)
    type = models.CharField(max_length=16, choices=Type.choices, default=Type.BUSINESS)
    tier = models.CharField(max_length=16, choices=Tier.choices, default=Tier.STANDARD)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    address_line1 = models.CharField(max_length=200, blank=True)
    address_line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True)
    region = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=2, blank=True, help_text="ISO 3166-1 alpha-2")
    notes = models.TextField(blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("name",)
        indexes = [models.Index(fields=("organization", "name"))]
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "name"), condition=Q(archived_at__isnull=True), name="uniq_active_customer_name"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class CustomerContact(BaseModel):
    """A person at a customer. Linking `user` gives them customer-portal access."""

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="contacts")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="customer_contacts"
    )
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    job_title = models.CharField(max_length=100, blank=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ("-is_primary", "name")
        constraints = [
            models.UniqueConstraint(fields=("customer",), condition=Q(is_primary=True), name="one_primary_contact"),
            models.UniqueConstraint(
                fields=("customer", "user"), condition=Q(user__isnull=False), name="uniq_contact_user"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.customer})"
