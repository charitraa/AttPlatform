from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("ai/analyses", views.AnalysisViewSet, basename="ai-analysis")
router.register("ai/recommendations", views.RecommendationViewSet, basename="ai-recommendation")
router.register("ai/insights", views.InsightViewSet, basename="ai-insight")

urlpatterns = [
    path("tickets/<uuid:ticket_pk>/ai/", views.TicketAIView.as_view(), name="ticket-ai"),
    path("ai/assistant/", views.AssistantView.as_view(), name="ai-assistant"),
    path("ai/status/", views.AIStatusView.as_view(), name="ai-status"),
    *router.urls,
]
