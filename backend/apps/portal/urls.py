from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("portal/tickets", views.PortalTicketViewSet, basename="portal-ticket")

urlpatterns = [
    path("portal/options/", views.PortalOptionsView.as_view(), name="portal-options"),
    path("portal/feedback/", views.FeedbackView.as_view(), name="portal-feedback"),
    *router.urls,
]
