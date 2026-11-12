from django.apps import AppConfig


class AIConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai"
    label = "ai"
    verbose_name = "AI engine"

    def ready(self):
        from . import handlers  # noqa: F401 - registers domain-event subscribers
