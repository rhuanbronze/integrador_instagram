import io

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.database.base import Base


def migrate(connection, action="upgrade", revision="head"):
    config = Config("alembic.ini")
    config.attributes["connection"] = connection
    getattr(command, action)(config, revision)


def test_upgrade_views_no_model_drift_and_downgrade():
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        migrate(connection)
        tables = inspect(connection).get_table_names()
        assert set(Base.metadata.tables) <= set(tables)
        assert len(inspect(connection).get_view_names()) == 6
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []
        migrate(connection, "downgrade", "base")
        assert inspect(connection).get_table_names() == ["alembic_version"]
        assert inspect(connection).get_view_names() == []
    engine.dispose()


def test_mysql_offline_ddl_includes_microseconds_and_guarded_rates():
    output = io.StringIO()
    config = Config("alembic.ini", output_buffer=output)
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    assert "DATETIME(6)" in sql
    assert "AUTO_INCREMENT" in sql
    assert "NULLIF(i.reach, 0)" in sql
    assert "ROW_NUMBER() OVER" in sql
    assert "UNIQUE (media_id, collected_at)" in sql
    assert "uq_account_insights_period" in sql
    assert "uq_audience_daily_bucket" in sql
    assert "CREATE VIEW vw_instagram_audience_demographics" in sql


def test_latest_view_tie_break_and_zero_division():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        migrate(connection)
        connection.execute(
            text("""
            INSERT INTO instagram_accounts
            (id, instagram_user_id, active, created_at, updated_at)
            VALUES (1, '123', 1, '2026-10-05', '2026-10-05')
        """)
        )
        connection.execute(
            text("""
            INSERT INTO instagram_media
            (id, account_id, instagram_media_id, published_at,
             first_seen_at, last_seen_at, created_at, updated_at)
            VALUES (1, 1, '180', '2026-10-05', '2026-10-05',
                    '2026-10-05', '2026-10-05', '2026-10-05')
        """)
        )
        for row_id, instant, views, reach in [
            (1, "2026-10-05 08:00:00", 2000, 20),
            (2, "2026-10-05 14:00:00", 2800, 0),
        ]:
            connection.execute(
                text("""
                INSERT INTO instagram_media_insights
                (id, media_id, collected_at, snapshot_date, views, reach, total_interactions,
                 shares, saved, created_at, updated_at)
                VALUES (:id, 1, :instant, '2026-10-05', :views, :reach, 10, 2, 3,
                        '2026-10-05', '2026-10-05')
            """),
                {"id": row_id, "instant": instant, "views": views, "reach": reach},
            )
        rows = connection.execute(text("SELECT * FROM vw_instagram_media_performance")).mappings()
        result = rows.one()
        assert result["views"] == 2800
        assert result["engagement_rate_reach"] is None
        assert result["share_rate"] is None
        assert result["save_rate"] is None
        connection.execute(text("UPDATE instagram_media_insights SET reach=100 WHERE id=2"))
        result = (
            connection.execute(text("SELECT * FROM vw_instagram_media_performance"))
            .mappings()
            .one()
        )
        assert result["engagement_rate_reach"] == 10
        assert result["share_rate"] == 2
        assert result["save_rate"] == 3
    engine.dispose()
