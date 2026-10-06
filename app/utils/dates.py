"""UTC instants and local calendar boundaries."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    return datetime.now(UTC)


def parse_timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Instagram timestamp must include timezone")
    return result.astimezone(UTC)


def snapshot_date(instant: datetime, timezone: str) -> date:
    return instant.astimezone(ZoneInfo(timezone)).date()


def previous_day_window(instant: datetime, timezone: str) -> tuple[date, datetime, datetime]:
    """The last complete local day, expressed with UTC request boundaries."""
    zone = ZoneInfo(timezone)
    end_day = snapshot_date(instant, timezone)
    day = end_day - timedelta(days=1)
    return (
        day,
        datetime.combine(day, time.min, zone).astimezone(UTC),
        datetime.combine(end_day, time.min, zone).astimezone(UTC),
    )
