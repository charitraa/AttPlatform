from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("notifications", views.NotificationViewSet, basename="notification")

urlpatterns = [
    path("notifications/preferences/", views.PreferencesView.as_view(), name="notification-preferences"),
    path("notifications/channels/", views.ChannelsView.as_view(), name="notification-channels"),
    path("notifications/telegram/link/", views.TelegramLinkView.as_view(), name="notification-telegram-link"),
    path("notifications/telegram/check/", views.TelegramCheckView.as_view(), name="notification-telegram-check"),
    *router.urls,
]
