"""
Work order state machine.

Dispatchers (work_orders.manage) assign, unassign and cancel. The assigned
technician (work_orders.execute) moves the job through the field steps.
"""

from .models import WorkOrderStatus as S

# to_status -> statuses it may come from
TECHNICIAN_STEPS: dict[str, frozenset[str]] = {
    S.ACCEPTED: frozenset({S.ASSIGNED}),
    S.EN_ROUTE: frozenset({S.ACCEPTED}),
    S.ON_SITE: frozenset({S.EN_ROUTE, S.ACCEPTED}),
    S.IN_PROGRESS: frozenset({S.ON_SITE}),
    S.COMPLETED: frozenset({S.IN_PROGRESS}),
}
# A technician may hand an assigned/accepted job back (decline) → created.
TECHNICIAN_DECLINE_FROM = frozenset({S.ASSIGNED, S.ACCEPTED})
CANCELLABLE_FROM = frozenset({S.CREATED, S.ASSIGNED, S.ACCEPTED, S.EN_ROUTE, S.ON_SITE, S.IN_PROGRESS})
TERMINAL = frozenset({S.COMPLETED, S.CANCELLED})


def next_steps(status: str, *, is_assigned_technician: bool, can_manage: bool) -> list[str]:
    steps = []
    if is_assigned_technician:
        steps += [to for to, sources in TECHNICIAN_STEPS.items() if status in sources]
    if can_manage and status in CANCELLABLE_FROM:
        steps.append(S.CANCELLED)
    return steps
