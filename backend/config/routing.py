from django.urls import path

from apps.core.consumers import SystemConsumer

websocket_urlpatterns = [
    path("ws/system/", SystemConsumer.as_asgi()),
]
