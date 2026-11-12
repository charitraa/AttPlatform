from django.contrib import admin

from .models import Integration, IntegrationLog, WebhookDelivery, WebhookEndpoint, WebhookEvent


@admin.register(Integration)
class IntegrationAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "kind", "provider", "is_enabled", "last_success_at", "last_error_at")
    list_filter = ("kind", "provider", "organization")
    exclude = ()  # credentials are a separate model and never shown here


@admin.register(WebhookEndpoint)
class WebhookEndpointAdmin(admin.ModelAdmin):
    list_display = ("url", "integration", "is_active")
    exclude = ("signing_secret_ciphertext",)


@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(admin.ModelAdmin):
    list_display = ("event_type", "endpoint", "status", "attempts", "response_code", "created_at")
    list_filter = ("status", "event_type")
    readonly_fields = [f.name for f in WebhookDelivery._meta.fields]


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("external_id", "integration", "status", "created_at", "processed_at")
    list_filter = ("status",)
    readonly_fields = [f.name for f in WebhookEvent._meta.fields]


@admin.register(IntegrationLog)
class IntegrationLogAdmin(admin.ModelAdmin):
    list_display = ("integration", "direction", "operation", "status", "duration_ms", "created_at")
    list_filter = ("status", "direction")
    readonly_fields = [f.name for f in IntegrationLog._meta.fields]
