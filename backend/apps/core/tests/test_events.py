import pytest
from django.db import transaction

from apps.core import events


@pytest.fixture(autouse=True)
def clean_bus():
    events.clear()
    yield
    events.clear()


def test_sync_handler_receives_payload():
    received = []
    events.subscribe("ticket.created")(received.append)
    events.publish("ticket.created", ticket_id="t-1")
    assert [e.payload for e in received] == [{"ticket_id": "t-1"}]


def test_failing_handler_does_not_break_publisher_or_others():
    received = []

    def broken(_event):
        raise ValueError("boom")

    events.subscribe("x")(broken)
    events.subscribe("x")(received.append)
    events.publish("x", n=1)
    assert len(received) == 1


@pytest.mark.django_db(transaction=True)
def test_on_commit_handler_runs_only_after_commit():
    received = []
    events.subscribe("ticket.created", on_commit=True)(received.append)
    with transaction.atomic():
        events.publish("ticket.created", ticket_id="t-2")
        assert received == []
    assert len(received) == 1


@pytest.mark.django_db(transaction=True)
def test_on_commit_handler_skipped_on_rollback():
    received = []
    events.subscribe("ticket.created", on_commit=True)(received.append)
    with pytest.raises(RuntimeError), transaction.atomic():
        events.publish("ticket.created", ticket_id="t-3")
        raise RuntimeError("rollback")
    assert received == []
