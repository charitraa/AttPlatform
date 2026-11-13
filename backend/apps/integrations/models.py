"""
Integrations: per-organization connections to external systems.

Secrets never live in `config`: they are `IntegrationCredential` rows holding
Fernet ciphertext, write-only through the API. Every external call is recorded in
`IntegrationLog` (summaries only, never secrets or full payloads).
"""

import secrets

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel

from . import crypto


class Integration(BaseModel):
    class Kind(models.TextChoices):
        WEBHOOK = "webhook", "Outbound webhooks"
        INBOUND = "inbound", "Inbound webhook"
        EMAIL = "email", "Email to ticket"
        SMS = "sms", "SMS"
        WHATSAPP = "whatsapp", "WhatsApp"
        TELEGRAM = "telegram", "Telegram"
        REST_API = "rest_api", "REST API"

    class Health(models.TextChoices):
        UNKNOWN = "unknown", "Not used yet"
        OK = "ok", "Working"
        ERROR = "error", "Failing"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    provider = models.CharField(max_length=32)
    name = models.CharField(max_length=100)
    config = models.JSONField(default=dict, blank=True, help_text="Non-secret settings only.")
    is_enabled = models.BooleanField(default=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ("name",)
        constraints = [models.UniqueConstraint(fields=("organization", "name"), name="uniq_integration_name")]

    def __str__(self) -> str:
        return self.name

    @property
    def health(self) -> str:
        if self.last_error_at and (not self.last_success_at or self.last_error_at > self.last_success_at):
            return self.Health.ERROR
        return self.Health.OK if self.last_success_at else self.Health.UNKNOWN

    # ---- secrets
    def secret(self, key: str) -> str | None:
        cred = self.credentials.filter(key=key).first()
        return crypto.decrypt(cred.ciphertext) if cred else None

    def set_secret(self, key: str, value: str) -> None:
        IntegrationCredential.objects.update_or_create(
            integration=self, key=key, defaults={"ciphertext": crypto.encrypt(value), "hint": crypto.hint(value)}
        )


class IntegrationCredential(models.Model):
    integration = models.ForeignKey(Integration, on_delete=models.CASCADE, related_name="credentials")
    key = models.CharField(max_length=50)
    ciphertext = models.TextField()
    hint = models.CharField(max_length=8, blank=True, help_text="At most the last 4 characters.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("integration", "key"), name="uniq_integration_secret")]

    def __str__(self) -> str:  # never the value
        return f"{self.integration_id}:{self.key}"


def new_signing_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


class WebhookEndpoint(BaseModel):
    """An outbound subscription: POST signed event envelopes to `url`."""

    integration = models.ForeignKey(Integration, on_delete=models.CASCADE, related_name="endpoints")
    url = models.URLField(max_length=500)
    events = ArrayField(models.CharField(max_length=50), default=list, help_text="Event types; empty = none.")
    signing_secret_ciphertext = models.TextField()
    is_active = models.BooleanField(default=True)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self) -> str:
        return self.url

    @property
    def signing_secret(self) -> str:
        return crypto.decrypt(self.signing_secret_ciphertext)

    def rotate_signing_secret(self) -> str:
        value = new_signing_secret()
        self.signing_secret_ciphertext = crypto.encrypt(value)
        return value


class WebhookDelivery(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Delivered"
        RETRYING = "retrying", "Retrying"
        FAILED = "failed", "Failed"

    endpoint = models.ForeignKey(WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries")
    event_id = models.UUIDField(help_text="Same for every delivery of one event (receivers dedupe on it).")
    event_type = models.CharField(max_length=50)
    payload = models.JSONField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    response_code = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.CharField(max_length=1000, blank=True)
    error = models.CharField(max_length=500, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("status", "next_retry_at"), name="webhook_retry_sweep")]
        constraints = [
            models.UniqueConstraint(fields=("endpoint", "event_id"), name="uniq_delivery_per_event"),
        ]


class WebhookEvent(BaseModel):
    """An inbound call, stored before processing (idempotent on `external_id`)."""

    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        PROCESSED = "processed", "Processed"
        IGNORED = "ignored", "Ignored"
        FAILED = "failed", "Failed"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    integration = models.ForeignKey(Integration, on_delete=models.CASCADE, related_name="inbound_events")
    external_id = models.CharField(max_length=200)
    headers = models.JSONField(default=dict)
    payload = models.JSONField()
    signature_valid = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RECEIVED)
    result = models.JSONField(default=dict, blank=True)
    error = models.CharField(max_length=500, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("integration", "external_id"), name="uniq_inbound_external_id"),
        ]


class IntegrationLog(models.Model):
    class Direction(models.TextChoices):
        OUTBOUND = "outbound", "Outbound"
        INBOUND = "inbound", "Inbound"

    class Status(models.TextChoices):
        OK = "ok", "OK"
        ERROR = "error", "Error"

    integration = models.ForeignKey(Integration, on_delete=models.CASCADE, related_name="logs")
    direction = models.CharField(max_length=10, choices=Direction.choices)
    operation = models.CharField(max_length=50)
    status = models.CharField(max_length=10, choices=Status.choices)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    request_summary = models.CharField(max_length=500, blank=True)
    response_summary = models.CharField(max_length=500, blank=True)
    error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [models.Index(fields=("integration", "-created_at"), name="integration_log_recent")]
        constraints = [models.CheckConstraint(condition=~Q(operation=""), name="integration_log_operation_set")]

    def __str__(self) -> str:
        return f"{self.operation} {self.status}"
