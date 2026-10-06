"""Parse scalar totals, time series and dimension-labelled breakdowns without guesses."""

from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from typing import Any


def number(value: Any) -> int | Decimal | None:
    if value is None or isinstance(value, bool) or isinstance(value, (dict, list)):
        return None
    try:
        parsed = Decimal(str(value))
        if not parsed.is_finite():
            return None
        return int(parsed) if parsed == parsed.to_integral_value() else parsed
    except (InvalidOperation, ValueError, TypeError):
        return None


def scalar(item: dict[str, Any] | None) -> int | Decimal | None:
    if not item:
        return None
    total = item.get("total_value")
    if isinstance(total, dict) and "value" in total:
        return number(total["value"])
    if total is not None and not isinstance(total, dict):
        return number(total)
    values = item.get("values") or []
    if not isinstance(values, list):
        return None
    parsed = [number(row.get("value")) for row in values if isinstance(row, dict)]
    # Unknown/missing buckets must not become a misleading partial total.
    if not parsed or any(value is None for value in parsed):
        return None
    return sum(parsed)


def breakdown_rows(item: dict[str, Any] | None) -> Iterator[tuple[dict[str, str], int | Decimal]]:
    if not item:
        return
    total = item.get("total_value") or {}
    containers = [total] if isinstance(total, dict) else []
    series = item.get("values") or []
    if isinstance(series, list):
        containers += [row for row in series if isinstance(row, dict)]
    containers.append(item)
    for container in containers:
        for breakdown in container.get("breakdowns") or []:
            if not isinstance(breakdown, dict):
                continue
            keys = breakdown.get("dimension_keys") or []
            for result in breakdown.get("results") or []:
                if not isinstance(result, dict):
                    continue
                values = result.get("dimension_values") or []
                value = number(result.get("value"))
                if value is not None and len(keys) == len(values):
                    yield dict(zip(keys, map(str, values), strict=True)), value


def follows_and_unfollows(item: dict[str, Any] | None) -> dict[str, int | None]:
    result: dict[str, int | None] = {"follows": None, "unfollows": None}
    # follow_type labels identify actions. NON_FOLLOWER is not an unfollow action.
    labels = {
        "FOLLOW": "follows",
        "FOLLOWS": "follows",
        "UNFOLLOW": "unfollows",
        "UNFOLLOWS": "unfollows",
    }
    for dimensions, value in breakdown_rows(item):
        column = labels.get(dimensions.get("follow_type", "").upper())
        if column:
            result[column] = (result[column] or 0) + int(value)
    # Some versions return named action values directly, not an overall net count.
    if item:
        rows = item.get("values") or []
        if not isinstance(rows, list):
            return result
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw = row.get("value")
            if isinstance(raw, dict):
                for key, value in raw.items():
                    column = labels.get(str(key).upper())
                    parsed = number(value)
                    if column and parsed is not None:
                        result[column] = (result[column] or 0) + int(parsed)
    return result
