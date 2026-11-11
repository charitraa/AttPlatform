from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """
    Append-only security record. Rows are never updated or deleted by the
    application; `save()` refuses updates and there is no delete path in the API.
    """

    class ActorType(models.TextChoices):
        USER = "user", "User"
        SYSTEM = "system", "System"
        AI = "ai", "AI"
        ANONYMOUS = "anonymous", "Anonymous"

    id = models.BigAutoField(primary_key=True)
    organization = models.ForeignKey(
        "organizations.Organization", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor_type = models.CharField(max_length=16, choices=ActorType.choices, default=ActorType.USER)
    action = models.CharField(max_length=64, db_index=True)  # e.g. "auth.login_failed", "membership.role_changed"
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    changes = models.JSONField(default=dict, blank=True)  # never contains secrets or passwords
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("organization", "created_at")),
            models.Index(fields=("target_type", "target_id")),
        ]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}"

    def save(self, *args, **kwargs):
        if self.pk is not None and not self._state.adding:
            raise RuntimeError("AuditLog entries are append-only.")
        super().save(*args, **kwargs)
