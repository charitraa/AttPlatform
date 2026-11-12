"""
In-process domain event bus.

Modules publish events (e.g. "ticket.created") without knowing who consumes them.
Handlers registered with `on_commit=True` run only after the surrounding database
transaction commits — use this for anything that enqueues Celery tasks, so workers
never observe uncommitted rows.

    from apps.core import events

    @events.subscribe("ticket.created", on_commit=True)
    def enqueue_ai_analysis(event: events.Event) -> None:
        analyze_ticket.delay(event.payload["ticket_id"])

    events.publish("ticket.created", organization_id=org.id, ticket_id=str(ticket.id))
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Event:
    name: str
    payload: dict
    occurred_at: datetime = field(default_factory=timezone.now)


Handler = Callable[[Event], None]
_handlers: dict[str, list[tuple[Handler, bool]]] = defaultdict(list)


def subscribe(name: str, *, on_commit: bool = False) -> Callable[[Handler], Handler]:
    def decorator(fn: Handler) -> Handler:
        if (fn, on_commit) not in _handlers[name]:
            _handlers[name].append((fn, on_commit))
        return fn

    return decorator


def _run(handler: Handler, event: Event) -> None:
    try:
        handler(event)
    except Exception:  # one failing subscriber must not break the publisher
        logger.exception("Event handler %s failed for %s", getattr(handler, "__qualname__", handler), event.name)


def publish(name: str, **payload) -> Event:
    event = Event(name=name, payload=payload)
    for handler, deferred in list(_handlers.get(name, ())):
        if deferred:
            transaction.on_commit(partial(_run, handler, event))
        else:
            _run(handler, event)
    return event


def clear() -> None:
    """Remove all handlers (tests only)."""
    _handlers.clear()
