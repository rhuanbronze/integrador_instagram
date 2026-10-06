from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import StatementError

from app.collectors.account_collector import followers_delta, save_daily
from app.collectors.media_collector import upsert_media
from app.models import InstagramAccountDaily, InstagramMedia, InstagramMediaInsights


@pytest.mark.parametrize(
    "current,previous,expected",
    [
        (170, 100, 70),
        (80, 100, -20),
        (0, 0, 0),
        (None, 100, None),
        (100, None, None),
    ],
)
def test_followers_delta(current, previous, expected):
    assert followers_delta(current, previous) == expected


def test_daily_rerun_uses_previous_day_not_earlier_today(session, account, now):
    save_daily(session, account.id, {"followers_count": 100}, now - timedelta(days=1), "UTC")
    save_daily(session, account.id, {"followers_count": 150}, now, "UTC")
    save_daily(session, account.id, {"followers_count": 170}, now + timedelta(hours=1), "UTC")
    session.commit()
    rows = list(
        session.scalars(
            select(InstagramAccountDaily).order_by(
                InstagramAccountDaily.snapshot_date,
            )
        )
    )
    assert len(rows) == 2
    assert rows[0].followers_delta is None
    assert rows[1].followers_delta == 70


def test_media_upsert_preserves_identity_first_seen_and_unknown_type(session, account, now):
    data = {
        "id": "180",
        "timestamp": now.isoformat(),
        "media_type": "FUTURE_FORMAT",
        "like_count": 3,
    }
    media, inserted = upsert_media(session, account.id, data, now)
    session.commit()
    original_id = media.id
    media, inserted_again = upsert_media(
        session, account.id, {**data, "like_count": 99}, now + timedelta(hours=6)
    )
    session.commit()
    assert inserted and not inserted_again
    assert media.id == original_id and media.like_count == 99
    assert media.media_type == "FUTURE_FORMAT"
    assert media.first_seen_at == now and media.last_seen_at == now + timedelta(hours=6)
    assert session.scalar(select(func.count()).select_from(InstagramMedia)) == 1


def test_multiple_intraday_snapshots_are_preserved(session, account, now):
    media, _ = upsert_media(session, account.id, {"id": "180", "timestamp": now.isoformat()}, now)
    for hours, views in [(0, 2000), (6, 2800), (12, 3500), (24, 5200)]:
        instant = now + timedelta(hours=hours)
        session.add(
            InstagramMediaInsights(
                media_id=media.id, collected_at=instant, snapshot_date=instant.date(), views=views
            )
        )
    session.commit()
    session.expire_all()
    rows = list(
        session.scalars(
            select(InstagramMediaInsights).order_by(
                InstagramMediaInsights.collected_at,
            )
        )
    )
    assert [row.views for row in rows] == [2000, 2800, 3500, 5200]
    assert all(row.collected_at.tzinfo == UTC for row in rows)


def test_naive_timestamps_rejected(session, account):
    session.add(
        InstagramAccountDaily(
            account_id=account.id,
            snapshot_date=datetime.now().date(),
            collected_at=datetime(2026, 10, 5),
        )
    )
    with pytest.raises(StatementError, match="Naive datetime rejected"):
        session.flush()
