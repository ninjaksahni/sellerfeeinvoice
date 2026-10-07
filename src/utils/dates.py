import re
from datetime import datetime, timezone

# Wed Sep 30 17:30:00 UTC 2020
END_DATE_RE = re.compile(
    r"^[A-Za-z]{3}\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(\d{1,2})\s+"
    r"(\d{2}:\d{2}:\d{2})\s+"
    r"UTC\s+"
    r"(\d{4})$"
)

MONTH_ABBR = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def parse_end_date_utc(raw: str) -> datetime:
    text = " ".join(raw.split())
    match = END_DATE_RE.match(text)
    if not match:
        raise ValueError(f"Unrecognized End Date format: {raw!r}")

    month_abbr, day, time_part, year = match.groups()
    month = MONTH_ABBR[month_abbr]
    dt = datetime.strptime(
        f"{year}-{month:02d}-{int(day):02d} {time_part}",
        "%Y-%m-%d %H:%M:%S",
    )
    return dt.replace(tzinfo=timezone.utc)


def end_date_in_month(end_date: datetime, year: int, month: int) -> bool:
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=timezone.utc)
    return end_date.year == year and end_date.month == month


def first_day_of_month_utc(year: int, month: int) -> datetime:
    return datetime(year, month, 1, tzinfo=timezone.utc)
