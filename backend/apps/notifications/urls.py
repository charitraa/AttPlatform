from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("notifications", views.NotificationViewSet, basename="notification")

urlpatterns = [
    path("notifications/preferences/", views.PreferencesView.as_view(), name="notification-preferences"),
    *router.urls,
]
