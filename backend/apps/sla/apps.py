from django.apps import AppConfig


class SLAConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sla"
    label = "sla"
    verbose_name = "SLA"

    def ready(self):
        from . import handlers  # noqa: F401 - registers domain-event subscribers and signals
