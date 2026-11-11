"""System WebSocket consumer — verifies the real-time pipeline end to end.

Authenticated, organization-scoped event consumers arrive in Phase 2/6
(`/ws/events/`). This one carries no tenant data.
"""
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings


class SystemConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        await self.accept()
        await self.send_json({"type": "system.welcome", "version": settings.APP_VERSION})

    async def receive_json(self, content, **kwargs):
        if isinstance(content, dict) and content.get("type") == "ping":
            await self.send_json({"type": "pong"})
        else:
            await self.send_json({"type": "error", "message": "Unsupported message type."})
