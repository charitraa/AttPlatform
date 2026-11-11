from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AttachmentDownloadView, TicketCategoryViewSet, TicketViewSet

router = DefaultRouter()
router.register("tickets", TicketViewSet, basename="ticket")
router.register("ticket-categories", TicketCategoryViewSet, basename="ticket-category")

urlpatterns = [
    *router.urls,
    path(
        "tickets/<uuid:ticket_pk>/attachments/<uuid:pk>/download/",
        AttachmentDownloadView.as_view(),
        name="ticket-attachment-download",
    ),
]
