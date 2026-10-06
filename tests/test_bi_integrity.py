"""Daily BI uniqueness, value updates and migration of existing duplicated datasets."""

import os
from datetime import timedelta

import httpx
import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.clients.instagram_client import InstagramClient
from app.collectors.account_insights_collector import collect_account_insights, collect_audience
from app.models import InstagramAccountInsights, InstagramAudienceDemographics


async def test_account_period_upsert_updates_metrics_and_collected_at(
    settings, session, account, now
):
    value = 10
    unsupported_reposts = False
    warnings = []

    def handler(request):
        metric = request.url.params["metric"]
        if metric == "reposts" and unsupported_reposts:
            return httpx.Response(400, json={"error": {"code": 100, "message": "Invalid metric"}})
        return httpx.Response(
            200, json={"data": [{"name": metric, "total_value": {"value": value}}]}
        )

    client = InstagramClient(settings, transport=httpx.MockTransport(handler))
    try:
        assert await collect_account_insights(client, session, account, now, warnings.append)
        session.commit()
        original = session.scalar(select(InstagramAccountInsights))
        original_id = original.id
        assert original.views == original.reposts == 10
        value = 25
        unsupported_reposts = True
        later = now + timedelta(hours=6)
        assert not await collect_account_insights(client, session, account, later, warnings.append)
        session.commit()
        rows = list(session.scalars(select(InstagramAccountInsights)))
        assert len(rows) == 1
        assert rows[0].id == original_id and rows[0].views == 25
        assert rows[0].reposts is None and rows[0].collected_at == later
        assert any("reposts" in warning for warning in warnings)
        assert await collect_account_insights(
            client,
            session,
            account,
            now + timedelta(days=1),
            warnings.append,
        )
        session.commit()
        assert len(list(session.scalars(select(InstagramAccountInsights)))) == 2
    finally:
        await client.close()


async def test_audience_upsert_updates_daily_bucket_without_duplicates(
    settings, session, account, now
):
    value = 1234

    def handler(request):
        metric = request.url.params["metric"]
        if metric != "follower_demographics" or request.url.params["breakdown"] != "city":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "name": metric,
                        "total_value": {
                            "breakdowns": [
                                {
                                    "dimension_keys": ["city"],
                                    "results": [
                                        {"dimension_values": ["Cuiabá"], "value": value},
                                    ],
                                }
                            ],
                        },
                    }
                ]
            },
        )

    client = InstagramClient(settings, transport=httpx.MockTransport(handler))
    try:
        assert await collect_audience(client, session, account, now, lambda _: None) == (1, 0)
        session.commit()
        original_id = session.scalar(select(InstagramAudienceDemographics)).id
        value = 1500
        later = now + timedelta(hours=6)
        assert await collect_audience(client, session, account, later, lambda _: None) == (0, 1)
        session.commit()
        rows = list(session.scalars(select(InstagramAudienceDemographics)))
        assert len(rows) == 1
        assert rows[0].id == original_id
        assert rows[0].metric_value == 1500 and rows[0].collected_at == later
        assert await collect_audience(
            client,
            session,
            account,
            now + timedelta(days=1),
            lambda _: None,
        ) == (1, 0)
        session.commit()
        assert len(list(session.scalars(select(InstagramAudienceDemographics)))) == 2
    finally:
        await client.close()


def seed_legacy_data(connection):
    connection.execute(
        text("""
        INSERT INTO instagram_accounts
        (id, instagram_user_id, username, active, created_at, updated_at)
        VALUES (1, '123', 'legacy-account', 1, '2026-10-05 00:00:00', '2026-10-05 00:00:00')
    """)
    )
    for row_id, period, instant, views in [
        (1, "2026-10-04", "2026-10-05 08:00:00", 10),
        (2, "2026-10-04", "2026-10-05 14:00:00", 20),
        (3, "2026-10-04", "2026-10-05 14:00:00", 30),
        (4, "2026-10-03", "2026-10-05 08:00:00", 40),
    ]:
        connection.execute(
            text("""
            INSERT INTO instagram_account_insights
            (id, account_id, period_start, period_end, collected_at, views, created_at, updated_at)
            VALUES (:id, 1, :period, :period, :instant, :views, :instant, :instant)
        """),
            {"id": row_id, "period": period, "instant": instant, "views": views},
        )
    for row_id, day, instant, audience, breakdown, label, value in [
        (1, "2026-10-05", "2026-10-05 14:00:00", "followers", "city", "Cuiabá", 10),
        (2, "2026-10-05", "2026-10-05 08:00:00", "followers", "city", "Cuiabá", 20),
        (3, "2026-10-05", "2026-10-05 14:00:00", "followers", "city", "Cuiabá", 30),
        (4, "2026-10-06", "2026-10-06 08:00:00", "followers", "city", "Cuiabá", 40),
        (5, "2026-10-05", "2026-10-05 08:00:00", "engaged", "city", "Cuiabá", 50),
        (6, "2026-10-05", "2026-10-05 08:00:00", "followers", "age", "25-34", 60),
    ]:
        connection.execute(
            text("""
            INSERT INTO instagram_audience_demographics
            (id, account_id, snapshot_date, audience_type, breakdown_type, breakdown_value,
             metric_value, collected_at)
            VALUES (:id, 1, :day, :audience, :breakdown, :label, :value, :instant)
        """),
            {
                "id": row_id,
                "day": day,
                "instant": instant,
                "audience": audience,
                "breakdown": breakdown,
                "label": label,
                "value": value,
            },
        )
    connection.execute(
        text("""
        INSERT INTO instagram_media
        (id, account_id, instagram_media_id, published_at, first_seen_at, last_seen_at,
         created_at, updated_at) VALUES (1, 1, '180', '2026-10-05 00:00:00',
          '2026-10-05 00:00:00', '2026-10-05 00:00:00',
          '2026-10-05 00:00:00', '2026-10-05 00:00:00')
    """)
    )
    for row_id, instant in [(1, "2026-10-05 08:00:00"), (2, "2026-10-05 14:00:00")]:
        connection.execute(
            text("""
            INSERT INTO instagram_media_insights
            (id, media_id, collected_at, snapshot_date, views, follows, profile_visits,
             avg_watch_time_ms, total_watch_time_ms, skip_rate, created_at, updated_at)
            VALUES (:id, 1, :instant, '2026-10-05', :views, 7, 8, 900, 1800, 12.3456,
                    :instant, :instant)
        """),
            {"id": row_id, "instant": instant, "views": row_id * 100},
        )
    connection.commit()


@pytest.mark.parametrize("backend", ["sqlite", "mysql"])
def test_incremental_upgrade_existing_duplicates_views_and_downgrade(backend):
    if backend == "mysql" and os.getenv("RUN_MYSQL_INTEGRATION") != "1":
        pytest.skip("Requires disposable MySQL Docker test database")
    url = (
        "mysql+pymysql://ig_test:development-only@127.0.0.1:13306/instagram_bi_test?charset=utf8mb4"
        if backend == "mysql"
        else "sqlite://"
    )
    engine = create_engine(url, hide_parameters=True)
    config = Config("alembic.ini")
    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0001_initial")
            seed_legacy_data(connection)
            media_before = list(
                connection.execute(text("SELECT * FROM instagram_media_insights ORDER BY id"))
            )
            command.upgrade(config, "head")
            connection.commit()
            command.check(config)
            assert list(
                connection.execute(
                    text("SELECT id, views FROM instagram_account_insights ORDER BY id")
                )
            ) == [(3, 30), (4, 40)]
            assert list(
                connection.execute(
                    text("SELECT id, metric_value FROM instagram_audience_demographics ORDER BY id")
                )
            ) == [(3, 30), (4, 40), (5, 50), (6, 60)]
            assert (
                list(connection.execute(text("SELECT * FROM instagram_media_insights ORDER BY id")))
                == media_before
            )
            demographics = (
                connection.execute(
                    text(
                        "SELECT * FROM vw_instagram_audience_demographics ORDER BY snapshot_date, "
                        "audience_type, breakdown_type"
                    )
                )
                .mappings()
                .all()
            )
            assert len(demographics) == 4
            assert set(demographics[0]) == {
                "snapshot_date",
                "instagram_user_id",
                "username",
                "audience_type",
                "breakdown_type",
                "breakdown_value",
                "metric_value",
                "collected_at",
            }
            assert all(
                row["instagram_user_id"] == "123" and row["username"] == "legacy-account"
                for row in demographics
            )
            performance = (
                connection.execute(text("SELECT * FROM vw_instagram_media_performance"))
                .mappings()
                .one()
            )
            assert performance["views"] == 200
            for field, expected in {
                "follows": 7,
                "profile_visits": 8,
                "avg_watch_time_ms": 900,
                "total_watch_time_ms": 1800,
                "skip_rate": 12.3456,
            }.items():
                assert float(performance[field]) == expected
            assert (
                "reposts"
                in connection.execute(text("SELECT * FROM vw_instagram_account_insights")).keys()
            )
            assert (
                connection.scalar(text("SELECT COUNT(reposts) FROM instagram_account_insights"))
                == 0
            )
            connection.commit()
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text("""
                    INSERT INTO instagram_account_insights
                    (account_id, period_start, period_end, collected_at, created_at, updated_at)
                    SELECT account_id, period_start, period_end, collected_at,
                           created_at, updated_at
                    FROM instagram_account_insights WHERE id=3
                """)
                )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text("""
                    INSERT INTO instagram_audience_demographics
                    (account_id, snapshot_date, audience_type, breakdown_type, breakdown_value,
                     metric_value, collected_at)
                    SELECT account_id, snapshot_date, audience_type, breakdown_type,
                           breakdown_value, metric_value, collected_at
                    FROM instagram_audience_demographics WHERE id=3
                """)
                )
            connection.commit()
            command.downgrade(config, "0001_initial")
            connection.commit()
            assert "reposts" not in {
                column["name"]
                for column in inspect(connection).get_columns("instagram_account_insights")
            }
            assert "vw_instagram_audience_demographics" not in inspect(connection).get_view_names()
            assert (
                "follows"
                not in connection.execute(
                    text("SELECT * FROM vw_instagram_media_performance")
                ).keys()
            )
            assert (
                list(connection.execute(text("SELECT * FROM instagram_media_insights ORDER BY id")))
                == media_before
            )
            connection.commit()
            command.upgrade(config, "head")
            connection.commit()
            command.check(config)
            command.downgrade(config, "base")
            connection.commit()
    finally:
        engine.dispose()
