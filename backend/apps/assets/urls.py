from rest_framework.routers import DefaultRouter

from .views import AssetCategoryViewSet, AssetViewSet

router = DefaultRouter()
router.register("assets", AssetViewSet, basename="asset")
router.register("asset-categories", AssetCategoryViewSet, basename="asset-category")
urlpatterns = router.urls
