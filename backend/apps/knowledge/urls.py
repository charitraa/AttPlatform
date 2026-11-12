from rest_framework.routers import DefaultRouter

from .views import ArticleViewSet

router = DefaultRouter()
router.register("knowledge/articles", ArticleViewSet, basename="knowledge-article")
urlpatterns = router.urls
