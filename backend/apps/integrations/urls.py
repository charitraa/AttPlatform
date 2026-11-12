from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("integrations", views.IntegrationViewSet, basename="integration")
router.register("webhook-endpoints", views.WebhookEndpointViewSet, basename="webhook-endpoint")
router.register("webhook-deliveries", views.WebhookDeliveryViewSet, basename="webhook-delivery")

urlpatterns = [
    path("webhooks/inbound/<uuid:integration_id>/", views.InboundWebhookView.as_view(), name="inbound-webhook"),
    *router.urls,
]
