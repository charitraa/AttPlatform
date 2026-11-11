"""
Ticket status state machine. Status changes only happen through
`services.transition_ticket`, which checks this map — never by assigning
`ticket.status` directly in views or serializers.
"""

from .models import TicketStatus as S

STAFF_TRANSITIONS: dict[str, frozenset[str]] = {
    S.NEW: frozenset({S.OPEN, S.ASSIGNED, S.IN_PROGRESS, S.PENDING_CUSTOMER, S.ESCALATED, S.RESOLVED, S.CLOSED}),
    S.OPEN: frozenset({S.ASSIGNED, S.IN_PROGRESS, S.PENDING_CUSTOMER, S.ESCALATED, S.RESOLVED, S.CLOSED}),
    S.ASSIGNED: frozenset({S.OPEN, S.IN_PROGRESS, S.PENDING_CUSTOMER, S.PENDING_PARTS, S.ESCALATED, S.RESOLVED}),
    S.IN_PROGRESS: frozenset({S.ASSIGNED, S.PENDING_CUSTOMER, S.PENDING_PARTS, S.ESCALATED, S.RESOLVED}),
    S.PENDING_CUSTOMER: frozenset({S.IN_PROGRESS, S.ESCALATED, S.RESOLVED, S.CLOSED}),
    S.PENDING_PARTS: frozenset({S.IN_PROGRESS, S.ESCALATED, S.RESOLVED}),
    S.ESCALATED: frozenset({S.ASSIGNED, S.IN_PROGRESS, S.PENDING_CUSTOMER, S.RESOLVED}),
    S.RESOLVED: frozenset({S.CLOSED, S.REOPENED}),
    S.CLOSED: frozenset({S.REOPENED}),
    S.REOPENED: frozenset({S.ASSIGNED, S.IN_PROGRESS, S.PENDING_CUSTOMER, S.ESCALATED, S.RESOLVED}),
}

# Customers may confirm a resolution (→ closed) or reopen it if the problem persists.
CUSTOMER_TRANSITIONS: dict[str, frozenset[str]] = {
    S.RESOLVED: frozenset({S.CLOSED, S.REOPENED}),
}

# Statuses that require resolution notes on entry.
REQUIRES_RESOLUTION = frozenset({S.RESOLVED})


def allowed_transitions(current: str, *, is_staff: bool) -> list[str]:
    table = STAFF_TRANSITIONS if is_staff else CUSTOMER_TRANSITIONS
    return sorted(table.get(current, frozenset()))
