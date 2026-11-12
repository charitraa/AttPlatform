from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.organizations.catalog import RoleCode
from apps.organizations.models import Membership


@receiver(post_save, sender=Membership, dispatch_uid="field_service.ensure_technician_profile")
def ensure_profile(sender, instance: Membership, **kwargs):
    """Anyone given the Field Technician role gets a technician profile."""
    if instance.is_active and instance.role.code == RoleCode.FIELD_TECHNICIAN:
        from .models import Technician

        Technician.objects.get_or_create(organization=instance.organization, user=instance.user)
