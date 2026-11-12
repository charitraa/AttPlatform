from django.contrib import admin

from .models import Appointment, ServiceArea, Skill, Technician, WorkOrder, WorkOrderEvidence


@admin.register(Technician)
class TechnicianAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "status", "max_daily_jobs", "location_sharing_enabled")
    list_filter = ("status",)


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = ("number", "title", "status", "technician", "customer", "scheduled_start")
    list_filter = ("status",)
    search_fields = ("title",)


admin.site.register([Skill, ServiceArea, Appointment, WorkOrderEvidence])
