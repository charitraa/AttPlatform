"""
Server → browser pushes over Channels groups.

Group names are derived server-side from the authenticated membership (see
consumers.EventsConsumer); payloads carry only types and IDs. Clients use them to
invalidate cached queries and re-read through the permission-checked REST API.
A broker outage must never break the business operation that triggered a push.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def user_group(user_id, organization_id) -> str:
    return f"u.{user_id}.{organization_id}"


def staff_group(organization_id) -> str:
    """Members who can see every ticket (tickets.view_all)."""
    return f"o.{organization_id}.staff"


def dispatch_group(organization_id) -> str:
    """Members who can see every work order (work_orders.view_all)."""
    return f"o.{organization_id}.dispatch"


def push(group: str, event: str, **data) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(group, {"type": "event.push", "event": event, "data": data})
    except Exception:  # noqa: BLE001 - real-time is best effort; REST stays authoritative
        logger.warning("Real-time push to %s failed", group, exc_info=True)
