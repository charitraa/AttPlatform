from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from apps.sla.business_time import Calendar, add_business_seconds, business_seconds_between, validate_schedule

KTM = ZoneInfo("Asia/Kathmandu")  # UTC+05:45, no DST
LDN = ZoneInfo("Europe/London")
WEEKDAYS_9_TO_5 = {d: [["09:00", "17:00"]] for d in ("mon", "tue", "wed", "thu", "fri")}
H = 3600


def cal(tz="Asia/Kathmandu", schedule=None, holidays=()):
    return Calendar.from_schedule(timezone=tz, schedule=schedule or WEEKDAYS_9_TO_5, holidays=holidays)


def local(tz, *args):
    return datetime(*args, tzinfo=tz)


def test_always_is_plain_arithmetic():
    start = datetime(2026, 11, 13, 22, 0, tzinfo=UTC)
    assert add_business_seconds(Calendar.always(), start, 4 * H) == start + timedelta(hours=4)
    assert business_seconds_between(Calendar.always(), start, start + timedelta(hours=4)) == 4 * H


def test_adds_within_and_across_days_and_weekends():
    c = cal()
    # Thursday 15:00 + 4h → 2h Thursday, 2h Friday → Friday 11:00
    assert add_business_seconds(c, local(KTM, 2026, 11, 12, 15), 4 * H) == local(KTM, 2026, 11, 13, 11)
    # Friday 16:00 + 2h → skips the weekend → Monday 10:00
    assert add_business_seconds(c, local(KTM, 2026, 11, 13, 16), 2 * H) == local(KTM, 2026, 11, 16, 10)
    # Starting outside hours (Saturday) begins at the next opening
    assert add_business_seconds(c, local(KTM, 2026, 11, 14, 12), 1 * H) == local(KTM, 2026, 11, 16, 10)
    # Ending exactly at closing time stays on that day
    assert add_business_seconds(c, local(KTM, 2026, 11, 12, 9), 8 * H) == local(KTM, 2026, 11, 12, 17)


def test_between_is_the_inverse_of_add():
    c = cal()
    start = local(KTM, 2026, 11, 12, 15, 20)
    for seconds in (60, 2 * H, 8 * H, 23 * H, 100 * H):
        assert business_seconds_between(c, start, add_business_seconds(c, start, seconds)) == pytest.approx(seconds)
    assert business_seconds_between(c, local(KTM, 2026, 11, 14, 10), local(KTM, 2026, 11, 15, 10)) == 0  # weekend


def test_holidays_and_split_shifts():
    c = cal(schedule={"mon": [["09:00", "12:00"], ["13:00", "17:00"]]}, holidays=[date(2026, 11, 16)])
    # Monday 16 Nov is a holiday → next Monday 23 Nov; lunch break is skipped
    assert add_business_seconds(c, local(KTM, 2026, 11, 13, 12), 4 * H) == local(KTM, 2026, 11, 23, 14)


def test_overnight_shift_with_24_00_and_midnight_start():
    c = cal(tz="UTC", schedule={d: [["00:00", "06:00"], ["22:00", "24:00"]] for d in ("mon", "tue")})
    # Monday 23:00 + 2h → 1h Monday night + 1h Tuesday early
    assert add_business_seconds(c, datetime(2026, 11, 16, 23, tzinfo=UTC), 2 * H) == datetime(2026, 11, 17, 1, tzinfo=UTC)


def test_dst_day_is_measured_in_real_seconds():
    # 25 Oct 2026: clocks go back in London (01:00–02:00 happens twice). 00:00–04:00 local is 5 real hours.
    c = cal(tz="Europe/London", schedule={"sun": [["00:00", "04:00"]]})
    start = local(LDN, 2026, 10, 25, 0)
    assert business_seconds_between(c, start, start.astimezone(UTC) + timedelta(hours=10)) == 5 * H
    assert add_business_seconds(c, start, 5 * H) == local(LDN, 2026, 10, 25, 4)


def test_naive_datetimes_are_rejected():
    with pytest.raises(ValueError):
        add_business_seconds(cal(), datetime(2026, 11, 12, 9), H)


@pytest.mark.parametrize(
    ("schedule", "message"),
    [
        ({}, "at least one"),
        ({"funday": [["09:00", "17:00"]]}, "Unknown weekday"),
        ({"mon": [["17:00", "09:00"]]}, "end after"),
        ({"mon": [["09:00", "13:00"], ["12:00", "17:00"]]}, "overlap"),
        ({"mon": [["09:00", "25:00"]]}, "Invalid time"),
    ],
)
def test_schedule_validation(schedule, message):
    with pytest.raises(ValueError, match=message):
        validate_schedule(schedule)
