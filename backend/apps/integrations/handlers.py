"""Domain events → outbound webhook deliveries (after commit)."""

from apps.core import events

from .services import EVENT_TYPES


def _dispatch(event: events.Event) -> None:
    from .services import dispatch_event

    dispatch_event(event.name, event.payload)


for _name in EVENT_TYPES:
    events.subscribe(_name, on_commit=True)(_dispatch)
