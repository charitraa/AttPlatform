from django.urls import path

from apps.core.consumers import SystemConsumer
from apps.notifications.consumers import EventsConsumer

websocket_urlpatterns = [
    path("ws/system/", SystemConsumer.as_asgi()),
    path("ws/events/", EventsConsumer.as_asgi()),
]
