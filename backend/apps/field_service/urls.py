from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("skills", views.SkillViewSet, basename="skill")
router.register("service-areas", views.ServiceAreaViewSet, basename="service-area")
router.register("technicians", views.TechnicianViewSet, basename="technician")
router.register("work-orders", views.WorkOrderViewSet, basename="work-order")

urlpatterns = [
    path(
        "work-orders/<uuid:wo_pk>/evidence/<uuid:pk>/download/",
        views.EvidenceDownloadView.as_view(),
        name="work-order-evidence-download",
    ),
    path("schedule/", views.ScheduleView.as_view(), name="schedule"),
    *router.urls,
]
