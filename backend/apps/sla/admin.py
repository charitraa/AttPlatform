from django.contrib import admin

from .models import BusinessHours, Holiday, SLAEvent, SLAInstance, SLAPolicy, SLATarget


class HolidayInline(admin.TabularInline):
    model = Holiday
    extra = 0


@admin.register(BusinessHours)
class BusinessHoursAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "timezone")
    list_filter = ("organization",)
    inlines = [HolidayInline]


class TargetInline(admin.TabularInline):
    model = SLATarget
    extra = 0


@admin.register(SLAPolicy)
class SLAPolicyAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "is_default", "is_active", "priority_order")
    list_filter = ("organization", "is_active")
    inlines = [TargetInline]


class EventInline(admin.TabularInline):
    model = SLAEvent
    extra = 0
    can_delete = False
    readonly_fields = ("type", "metric", "occurred_at", "payload", "actor")


@admin.register(SLAInstance)
class SLAInstanceAdmin(admin.ModelAdmin):
    list_display = ("ticket", "policy_name", "priority", "response_status", "resolution_status", "resolution_due_at")
    list_filter = ("organization", "resolution_status", "response_status", "priority")
    raw_id_fields = ("ticket",)
    inlines = [EventInline]
    readonly_fields = [f.name for f in SLAInstance._meta.fields]
