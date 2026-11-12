from django.apps import AppConfig


class FieldServiceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.field_service"
    label = "field_service"
    verbose_name = "Field service"

    def ready(self):
        from . import signals  # noqa: F401
