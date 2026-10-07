from datetime import datetime, timezone

import pytest

from src.utils.dates import end_date_in_month, first_day_of_month_utc, parse_end_date_utc


def test_parse_end_date_sample() -> None:
    raw = "Wed Sep 30 17:30:00 UTC 2020"
    dt = parse_end_date_utc(raw)
    assert dt == datetime(2020, 9, 30, 17, 30, 0, tzinfo=timezone.utc)


def test_parse_end_date_extra_whitespace() -> None:
    raw = "  Wed   Sep  30  17:30:00  UTC  2020  "
    dt = parse_end_date_utc(raw)
    assert dt.month == 9 and dt.year == 2020


def test_end_date_in_month_match() -> None:
    dt = parse_end_date_utc("Wed Sep 30 17:30:00 UTC 2020")
    assert end_date_in_month(dt, 2020, 9)
    assert not end_date_in_month(dt, 2020, 10)
    assert not end_date_in_month(dt, 2019, 9)


def test_first_day_of_month() -> None:
    assert first_day_of_month_utc(2020, 9) == datetime(2020, 9, 1, tzinfo=timezone.utc)


def test_parse_invalid_raises() -> None:
    with pytest.raises(ValueError):
        parse_end_date_utc("not a date")
