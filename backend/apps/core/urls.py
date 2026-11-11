from django.urls import path

from .views import HealthView, MetaView, ReadinessView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("health/ready/", ReadinessView.as_view(), name="health-ready"),
    path("meta/", MetaView.as_view(), name="meta"),
]
