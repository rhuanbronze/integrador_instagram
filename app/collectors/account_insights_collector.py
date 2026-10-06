from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.instagram_client import InstagramClient
from app.collectors.insights_parser import breakdown_rows, follows_and_unfollows, scalar
from app.collectors.metrics import (
    ACCOUNT_EXPECTED_UNSUPPORTED_METRICS,
    ACCOUNT_INSIGHT_METRICS,
    AUDIENCE_METRICS,
)
from app.models import InstagramAccount, InstagramAccountInsights, InstagramAudienceDemographics
from app.utils.dates import previous_day_window, snapshot_date


async def collect_account_insights(
    client: InstagramClient,
    session: Session,
    account: InstagramAccount,
    now: datetime,
    warning: Callable[[str], None],
) -> bool:
    """Upsert the last complete day's insights; return whether a row was inserted."""
    day, since, until = previous_day_window(now, client.settings.timezone)
    values = {}
    for metric, column in ACCOUNT_INSIGHT_METRICS.items():
        params = {
            "period": "day",
            "metric_type": "total_value",
            "since": int(since.timestamp()),
            "until": int(until.timestamp()),
        }
        if metric == "follows_and_unfollows":
            params["breakdown"] = "follow_type"
        item = await client.optional_metric(
            account.instagram_user_id,
            metric,
            params,
            warning,
            expected_unsupported=metric in ACCOUNT_EXPECTED_UNSUPPORTED_METRICS,
        )
        if metric == "follows_and_unfollows":
            parsed = follows_and_unfollows(item)
            if item and any(value is None for value in parsed.values()):
                warning("Follows/unfollows action breakdown unavailable or unrecognized")
            values.update(parsed)
        else:
            values[column] = scalar(item)
            if item and values[column] is None:
                warning(f"Metric {metric} has no numeric total")
    row = session.scalar(
        select(InstagramAccountInsights).where(
            InstagramAccountInsights.account_id == account.id,
            InstagramAccountInsights.period_start == day,
            InstagramAccountInsights.period_end == day,
        )
    )
    inserted = row is None
    if row is None:
        row = InstagramAccountInsights(
            account_id=account.id, period_start=day, period_end=day, collected_at=now
        )
        session.add(row)
    for column, value in values.items():
        setattr(row, column, value)
    row.collected_at = now
    session.flush()
    return inserted


async def collect_audience(
    client: InstagramClient,
    session: Session,
    account: InstagramAccount,
    now: datetime,
    warning: Callable[[str], None],
) -> tuple[int, int]:
    """Upsert daily audience buckets; return inserted/updated row counts."""
    inserted = 0
    updated = 0
    day = snapshot_date(now, client.settings.timezone)
    for metric, audience in AUDIENCE_METRICS.items():
        for breakdown in ("country", "city", "age", "gender"):
            item = await client.optional_metric(
                account.instagram_user_id,
                metric,
                {
                    "period": "lifetime",
                    "metric_type": "total_value",
                    "breakdown": breakdown,
                    "timeframe": "last_30_days",
                },
                warning,
            )
            found = False
            for dimensions, value in breakdown_rows(item):
                label = dimensions.get(breakdown)
                if label is None:
                    continue
                found = True
                row = session.scalar(
                    select(InstagramAudienceDemographics).where(
                        InstagramAudienceDemographics.account_id == account.id,
                        InstagramAudienceDemographics.snapshot_date == day,
                        InstagramAudienceDemographics.audience_type == audience,
                        InstagramAudienceDemographics.breakdown_type == breakdown,
                        InstagramAudienceDemographics.breakdown_value == label,
                    )
                )
                if row is None:
                    row = InstagramAudienceDemographics(
                        account_id=account.id,
                        snapshot_date=day,
                        audience_type=audience,
                        breakdown_type=breakdown,
                        breakdown_value=label,
                        metric_value=int(value),
                        collected_at=now,
                    )
                    session.add(row)
                    inserted += 1
                else:
                    row.metric_value = int(value)
                    row.collected_at = now
                    updated += 1
                session.flush()
            if item and not found:
                warning(f"Audience {audience}/{breakdown} absent or unrecognized")
    return inserted, updated
