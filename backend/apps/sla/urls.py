from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("sla/business-hours", views.BusinessHoursViewSet, basename="business-hours")
router.register("sla/policies", views.SLAPolicyViewSet, basename="sla-policy")

urlpatterns = [
    path("tickets/<uuid:ticket_id>/sla/", views.TicketSLAView.as_view(), name="ticket-sla"),
    path("sla/report/", views.SLAReportView.as_view(), name="sla-report"),
    *router.urls,
]
