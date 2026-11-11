from django.apps import AppConfig
from django.db.models.signals import post_migrate


class OrganizationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.organizations"
    label = "organizations"

    def ready(self):
        from .services import sync_roles_after_migrate

        # Keeps Role/Permission tables in step with catalog.py after every migrate/flush.
        post_migrate.connect(sync_roles_after_migrate, sender=self, dispatch_uid="organizations.sync_roles")
