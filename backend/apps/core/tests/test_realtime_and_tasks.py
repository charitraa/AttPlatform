import pytest
from channels.routing import URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from channels.testing import WebsocketCommunicator

from apps.core.tasks import ping
from config.asgi import application
from config.routing import websocket_urlpatterns


@pytest.mark.asyncio
async def test_system_websocket_welcome_and_ping():
    communicator = WebsocketCommunicator(application, "/ws/system/", headers=[(b"origin", b"http://localhost")])
    connected, _ = await communicator.connect()
    assert connected
    assert (await communicator.receive_json_from())["type"] == "system.welcome"
    await communicator.send_json_to({"type": "ping"})
    assert await communicator.receive_json_from() == {"type": "pong"}
    await communicator.disconnect()


@pytest.mark.asyncio
async def test_websocket_rejects_disallowed_origin(settings):
    # The validator reads ALLOWED_HOSTS when constructed, so build it after overriding.
    settings.ALLOWED_HOSTS = ["localhost"]
    app = AllowedHostsOriginValidator(URLRouter(websocket_urlpatterns))
    communicator = WebsocketCommunicator(app, "/ws/system/", headers=[(b"origin", b"https://evil.example")])
    connected, _ = await communicator.connect()
    assert not connected


def test_celery_ping_task_runs_eagerly():
    result = ping.delay().get(timeout=5)
    assert result["pong"] is True
