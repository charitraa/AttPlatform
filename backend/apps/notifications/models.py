from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel


class NotificationType(models.TextChoices):
    TICKET_ASSIGNED = "ticket_assigned", "Ticket assigned to me"
    CUSTOMER_REPLY = "customer_reply", "Customer replied on my ticket"
    TICKET_ESCALATED = "ticket_escalated", "Ticket escalated"
    TICKET_REOPENED = "ticket_reopened", "Customer reopened my ticket"
    SLA_WARNING = "sla_warning", "SLA at risk"
    SLA_BREACHED = "sla_breached", "SLA breached"
    WORK_ORDER_ASSIGNED = "work_order_assigned", "Work order assigned to me"
    WORK_ORDER_UPDATED = "work_order_updated", "Work order completed, handed back or cancelled"


class Channel(models.TextChoices):
    IN_APP = "in_app", "In-app"
    EMAIL = "email", "Email"
    WHATSAPP = "whatsapp", "WhatsApp"
    SMS = "sms", "SMS"
    TELEGRAM = "telegram", "Telegram"


# Defaults when a user has not chosen: email only for things that need action soon.
DEFAULT_ENABLED: dict[str, dict[str, bool]] = {
    NotificationType.TICKET_ASSIGNED: {Channel.IN_APP: True, Channel.EMAIL: True},
    NotificationType.CUSTOMER_REPLY: {Channel.IN_APP: True, Channel.EMAIL: False},
    NotificationType.TICKET_ESCALATED: {Channel.IN_APP: True, Channel.EMAIL: True},
    NotificationType.TICKET_REOPENED: {Channel.IN_APP: True, Channel.EMAIL: False},
    NotificationType.SLA_WARNING: {Channel.IN_APP: True, Channel.EMAIL: False},
    NotificationType.SLA_BREACHED: {Channel.IN_APP: True, Channel.EMAIL: True},
    NotificationType.WORK_ORDER_ASSIGNED: {Channel.IN_APP: True, Channel.EMAIL: True},
    NotificationType.WORK_ORDER_UPDATED: {Channel.IN_APP: True, Channel.EMAIL: False},
}


class Notification(BaseModel):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    type = models.CharField(max_length=32, choices=NotificationType.choices)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    link = models.CharField(max_length=300, blank=True, help_text="App path, e.g. /tickets/<id>")
    data = models.JSONField(default=dict, blank=True)
    in_app = models.BooleanField(default=True, help_text="False when the recipient only wants email for this type.")
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("recipient", "organization", "read_at", "created_at"), name="notif_inbox"),
        ]

    def __str__(self) -> str:
        return self.title


class NotificationDelivery(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name="deliveries")
    channel = models.CharField(max_length=10, choices=Channel.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=500, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(fields=("notification", "channel"), name="uniq_delivery_channel"),
        ]
        indexes = [models.Index(fields=("status", "created_at"), name="delivery_status")]


class NotificationPreference(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    type = models.CharField(max_length=32, choices=NotificationType.choices)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    enabled = models.BooleanField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("user", "organization", "type", "channel"), name="uniq_notif_pref"),
            models.CheckConstraint(condition=~Q(type=""), name="notif_pref_type_set"),
        ]

    def __str__(self) -> str:
        return f"{self.type}/{self.channel}: {'on' if self.enabled else 'off'}"


class ChatLink(models.Model):
    """A person's address on a chat channel that can't be typed in (Telegram chat ID), linked by the person."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    channel = models.CharField(max_length=10, choices=Channel.choices)
    address = models.CharField(max_length=64)
    display_name = models.CharField(max_length=100, blank=True)
    linked_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("user", "organization", "channel"), name="uniq_chat_link")]

    def __str__(self) -> str:
        return f"{self.user_id} {self.channel}"
