from django.contrib import admin

from .models import Notification, NotificationDelivery


class DeliveryInline(admin.TabularInline):
    model = NotificationDelivery
    extra = 0
    can_delete = False
    readonly_fields = ("channel", "status", "attempts", "last_error", "sent_at")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "recipient", "type", "organization", "created_at", "read_at")
    list_filter = ("type", "organization")
    search_fields = ("title", "recipient__email")
    raw_id_fields = ("recipient",)
    inlines = [DeliveryInline]
