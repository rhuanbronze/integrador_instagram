"""Retry delays for transient read requests."""

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


def retry_delay(attempt: int, retry_after: str | None = None) -> float:
    delay = float(2 ** (attempt + 1))
    if retry_after:
        try:
            return max(delay, float(retry_after))
        except ValueError:
            try:
                deadline = parsedate_to_datetime(retry_after)
                return max(delay, (deadline - datetime.now(UTC)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                pass
    return delay
