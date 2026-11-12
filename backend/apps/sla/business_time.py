"""
Business-time arithmetic for SLA clocks (pure functions, no database).

A `Calendar` is a weekly schedule of working intervals in a time zone plus a set of
holiday dates. `None` working hours means 24/7. All arithmetic is done on UTC
instants: Python subtracts two aware datetimes that share a tzinfo as wall-clock
times, which is wrong across DST changes, so local times are converted to UTC
before any subtraction or addition.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_SCAN_DAYS = 3 * 366  # a schedule with almost no working time still terminates


def parse_clock(value: str) -> tuple[int, int]:
    """'09:30' → (9, 30). '24:00' is allowed as an interval end (midnight next day)."""
    hh, mm = value.split(":")
    h, m = int(hh), int(mm)
    if not (0 <= h <= 24 and 0 <= m < 60) or (h == 24 and m != 0):
        raise ValueError(f"Invalid time '{value}'.")
    return h, m


def validate_schedule(schedule: dict) -> dict[str, list[list[str]]]:
    """Normalise and validate a weekly schedule; raises ValueError with a readable message."""
    if not isinstance(schedule, dict):
        raise ValueError("Working hours must be an object keyed by weekday.")
    unknown = set(schedule) - set(WEEKDAYS)
    if unknown:
        raise ValueError(f"Unknown weekday(s): {', '.join(sorted(unknown))}.")
    out: dict[str, list[list[str]]] = {}
    total = 0
    for day in WEEKDAYS:
        intervals = schedule.get(day) or []
        spans = []
        for item in intervals:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise ValueError(f"{day}: each interval is [start, end].")
            (sh, sm), (eh, em) = parse_clock(str(item[0])), parse_clock(str(item[1]))
            start, end = sh * 60 + sm, eh * 60 + em
            if end <= start:
                raise ValueError(f"{day}: {item[0]}–{item[1]} must end after it starts.")
            spans.append((start, end, [str(item[0]), str(item[1])]))
        spans.sort()
        for (_, prev_end, _), (start, _, raw) in zip(spans, spans[1:], strict=False):
            if start < prev_end:
                raise ValueError(f"{day}: intervals overlap at {raw[0]}.")
        total += sum(e - s for s, e, _ in spans)
        out[day] = [raw for _, _, raw in spans]
    if total == 0:
        raise ValueError("Add at least one working interval.")
    return out


@dataclass(frozen=True)
class Calendar:
    tz: ZoneInfo = field(default_factory=lambda: ZoneInfo("UTC"))
    # weekday index (0 = Monday) → [(start_minute, end_minute)], or None for 24/7
    hours: dict[int, tuple[tuple[int, int], ...]] | None = None
    holidays: frozenset[date] = frozenset()

    @classmethod
    def always(cls) -> Calendar:
        return cls()

    @classmethod
    def from_schedule(cls, *, timezone: str, schedule: dict, holidays=()) -> Calendar:
        normalised = validate_schedule(schedule)
        hours = {}
        for idx, day in enumerate(WEEKDAYS):
            spans = []
            for start, end in normalised[day]:
                (sh, sm), (eh, em) = parse_clock(start), parse_clock(end)
                spans.append((sh * 60 + sm, eh * 60 + em))
            hours[idx] = tuple(spans)
        return cls(tz=ZoneInfo(timezone), hours=hours, holidays=frozenset(holidays))

    @property
    def is_always(self) -> bool:
        return self.hours is None

    def _local_instant(self, d: date, minute: int) -> datetime:
        """UTC instant of local wall time `minute` minutes after midnight on `d`."""
        base = datetime.combine(d, time(0), tzinfo=self.tz) if minute < 24 * 60 else None
        if base is None:  # '24:00' → next day's midnight
            return datetime.combine(d + timedelta(days=1), time(0), tzinfo=self.tz).astimezone(UTC)
        local = datetime.combine(d, time(minute // 60, minute % 60), tzinfo=self.tz)
        return local.astimezone(UTC)

    def intervals_from(self, start: datetime) -> Iterator[tuple[datetime, datetime]]:
        """Working intervals (UTC) that end after `start`, in order; the first may begin before it."""
        assert self.hours is not None
        day = start.astimezone(self.tz).date() - timedelta(days=1)  # an overnight shift may still be running
        for _ in range(MAX_SCAN_DAYS):
            if day not in self.holidays:
                for s, e in self.hours[day.weekday()]:
                    a, b = self._local_instant(day, s), self._local_instant(day, e)
                    if b > start:
                        yield a, b
            day += timedelta(days=1)


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("Business-time arithmetic needs timezone-aware datetimes.")
    return dt.astimezone(UTC)


def add_business_seconds(cal: Calendar, start: datetime, seconds: float) -> datetime:
    """The instant `seconds` of working time after `start`."""
    start = _utc(start)
    if seconds <= 0:
        return start
    if cal.is_always:
        return start + timedelta(seconds=seconds)
    remaining = seconds
    for a, b in cal.intervals_from(start):
        begin = max(a, start)
        available = (b - begin).total_seconds()
        if remaining <= available:
            return begin + timedelta(seconds=remaining)
        remaining -= available
    raise ValueError("The working calendar has no working time in the next three years.")


def business_seconds_between(cal: Calendar, a: datetime, b: datetime) -> float:
    """Working seconds in [a, b); negative if b is before a."""
    a, b = _utc(a), _utc(b)
    if b < a:
        return -business_seconds_between(cal, b, a)
    if cal.is_always:
        return (b - a).total_seconds()
    total = 0.0
    for s, e in cal.intervals_from(a):
        if s >= b:
            break
        total += (min(e, b) - max(s, a)).total_seconds()
    return total
