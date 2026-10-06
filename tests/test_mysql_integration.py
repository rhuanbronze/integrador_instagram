"""Opt-in test against the disposable Docker database; never calls Instagram."""

import os
from datetime import timedelta

import httpx
import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select, text

from alembic import command
from app.clients.instagram_client import InstagramClient
from app.config import Settings
from app.database.base import Base
from app.database.session import build_engine, session_factory
from app.models import ETLRun, InstagramAccountInsights, InstagramMedia, InstagramMediaInsights
from app.services.instagram_service import InstagramService, JobBusyError
from app.utils.dates import utcnow


@pytest.mark.skipif(
    os.getenv("RUN_MYSQL_INTEGRATION") != "1",
    reason="Requires disposable MySQL Docker test database",
)
async def test_real_mysql_migrations_views_lock_and_collections():
    settings = Settings(
        _env_file=None,
        mysql_host="127.0.0.1",
        mysql_port=13306,
        mysql_database="instagram_bi_test",
        mysql_user="ig_test",
        mysql_password="development-only",
        instagram_access_token="fake-integration-token",
        instagram_user_id="",
        admin_api_key="fake-integration-key",
        audience_collection_enabled=False,
        collect_on_startup=False,
        scheduler_enabled=False,
    )
    engine = build_engine(settings)
    sessions = session_factory(engine)
    now = utcnow()

    def handler(request):
        if request.url.path.endswith("/me"):
            return httpx.Response(
                200,
                json={
                    "id": "123",
                    "username": "mysql-test",
                    "name": "Teste de integração",
                    "profile_picture_url": None,
                    "followers_count": 170,
                    "follows_count": 10,
                    "media_count": 2,
                },
            )
        if request.url.path.endswith("/me/media"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "180",
                            "timestamp": now.isoformat(),
                            "media_type": "VIDEO",
                            "media_product_type": "REELS",
                            "caption": "Teste 🌟",
                        },
                        {"id": "181", "timestamp": (now - timedelta(days=120)).isoformat()},
                    ]
                },
            )
        metric = request.url.params["metric"]
        if metric == "follows_and_unfollows":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(
            200,
            json={
                "data": [{"name": metric, "total_value": {"value": 0 if metric == "reach" else 42}}]
            },
        )

    client = InstagramClient(settings, transport=httpx.MockTransport(handler))
    service = InstagramService(settings, sessions, client)
    contender = InstagramService(settings, sessions, client)
    config = Config("alembic.ini")
    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            connection.commit()
            command.check(config)
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
            assert len(inspect(connection).get_view_names()) == 6
        for _ in range(2):
            await service.submit("all")
            with pytest.raises(JobBusyError):
                await contender.submit("media")
            await service.task
        with sessions() as session:
            runs = list(session.scalars(select(ETLRun)))
            assert len(runs) == 4
            assert all(run.status in {"SUCCESS", "SUCCESS_WITH_WARNINGS"} for run in runs)
            media = session.scalar(
                select(InstagramMedia).where(InstagramMedia.instagram_media_id == "180")
            )
            assert media.caption == "Teste 🌟"
            snapshots = list(session.scalars(select(InstagramMediaInsights)))
            assert len(snapshots) == 2
            assert len(list(session.scalars(select(InstagramAccountInsights)))) == 1
            assert snapshots[0].collected_at != snapshots[1].collected_at
            assert snapshots[0].collected_at.tzinfo is not None
            performance = (
                session.execute(
                    text(
                        "SELECT * FROM vw_instagram_media_performance "
                        "WHERE instagram_media_id='180'"
                    )
                )
                .mappings()
                .one()
            )
            assert performance["views"] == 42
            assert performance["engagement_rate_reach"] is None
            assert performance["share_rate"] is None
            assert performance["follows"] is None
            assert performance["profile_visits"] is None
            for field in (
                "avg_watch_time_ms",
                "total_watch_time_ms",
                "skip_rate",
            ):
                assert performance[field] == 42
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
            connection.commit()
            assert inspect(connection).get_table_names() == ["alembic_version"]
    finally:
        await service.shutdown()
        await contender.shutdown()
        await client.close()
        engine.dispose()
