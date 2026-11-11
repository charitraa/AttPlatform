from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from apps.accounts.urls import auth_urlpatterns, me_urlpatterns

api_v1 = [
    path("", include("apps.core.urls")),
    path("auth/", include(auth_urlpatterns)),
    path("me/", include(me_urlpatterns)),
    path("", include("apps.organizations.urls")),
    path("", include("apps.customers.urls")),
    path("", include("apps.assets.urls")),
    path("", include("apps.tickets.urls")),
    path("", include("apps.analytics.urls")),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(api_v1)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
