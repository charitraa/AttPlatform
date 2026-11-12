from django.contrib import admin

from .models import CustomerFeedback


@admin.register(CustomerFeedback)
class CustomerFeedbackAdmin(admin.ModelAdmin):
    list_display = ("rating", "customer", "ticket", "work_order", "created_at")
    list_filter = ("rating", "organization")
    readonly_fields = [f.name for f in CustomerFeedback._meta.fields]
