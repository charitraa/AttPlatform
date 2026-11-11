"""Abstract base models shared by every domain app."""
import uuid

from django.db import models


class TimeStampedModel(models.Model):
    """Timezone-aware creation/update timestamps (stored in UTC)."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDModel(models.Model):
    """UUID primary key for externally exposed resources (no enumeration)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class BaseModel(UUIDModel, TimeStampedModel):
    """Default base for domain entities: UUID PK + timestamps."""

    class Meta:
        abstract = True
        ordering = ("-created_at",)
