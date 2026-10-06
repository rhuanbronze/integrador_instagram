"""Unique daily BI datasets, optional reposts and expanded views."""

import sqlalchemy as sa

from alembic import op

revision = "0002_bi_data_integrity"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

ACCOUNT_VIEW = """
    SELECT i.*, a.instagram_user_id, a.username
    FROM instagram_account_insights i JOIN instagram_accounts a ON a.id = i.account_id
"""
AUDIENCE_VIEW = """
    SELECT d.snapshot_date, a.instagram_user_id, a.username, d.audience_type,
           d.breakdown_type, d.breakdown_value, d.metric_value, d.collected_at
    FROM instagram_audience_demographics d JOIN instagram_accounts a ON a.id = d.account_id
"""
MEDIA_PERFORMANCE_VIEW = """
    SELECT m.account_id, m.instagram_media_id, m.published_at, m.media_type,
           m.media_product_type, m.caption, m.permalink,
           i.views, i.reach, i.likes, i.comments, i.shares, i.saved, i.total_interactions,
           i.collected_at,
           100.0 * i.total_interactions / NULLIF(i.reach, 0) AS engagement_rate_reach,
           100.0 * i.shares / NULLIF(i.reach, 0) AS share_rate,
           100.0 * i.saved / NULLIF(i.reach, 0) AS save_rate{extra_columns}
    FROM instagram_media m
    LEFT JOIN vw_instagram_media_latest_insights i ON i.media_id = m.id
"""


def deduplicate(table: str, keys: str) -> None:
    """Retain the newest complete row per key; resolve timestamp ties by highest id."""
    # The windowed derived table is materialized on MySQL, avoiding target-table error 1093.
    op.execute(f"""
        DELETE FROM {table} WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY {keys} ORDER BY collected_at DESC, id DESC
                ) AS duplicate_rank FROM {table}
            ) ranked WHERE duplicate_rank > 1
        )
    """)


def upgrade():
    op.execute("DROP VIEW vw_instagram_account_insights")
    op.execute("DROP VIEW vw_instagram_media_performance")
    deduplicate("instagram_account_insights", "account_id, period_start, period_end")
    deduplicate(
        "instagram_audience_demographics",
        "account_id, snapshot_date, audience_type, breakdown_type, breakdown_value",
    )
    with op.batch_alter_table("instagram_account_insights") as batch:
        batch.add_column(sa.Column("reposts", sa.BigInteger(), nullable=True))
        batch.create_unique_constraint(
            "uq_account_insights_period", ["account_id", "period_start", "period_end"]
        )
    with op.batch_alter_table("instagram_audience_demographics") as batch:
        batch.create_unique_constraint(
            "uq_audience_daily_bucket",
            [
                "account_id",
                "snapshot_date",
                "audience_type",
                "breakdown_type",
                "breakdown_value",
            ],
        )
    op.execute(f"CREATE VIEW vw_instagram_account_insights AS {ACCOUNT_VIEW}")
    op.execute(f"CREATE VIEW vw_instagram_audience_demographics AS {AUDIENCE_VIEW}")
    sql = MEDIA_PERFORMANCE_VIEW.format(
        extra_columns=(
            ", i.follows, i.profile_visits, i.avg_watch_time_ms, i.total_watch_time_ms, i.skip_rate"
        )
    )
    op.execute(f"CREATE VIEW vw_instagram_media_performance AS {sql}")


def downgrade():
    op.execute("DROP VIEW vw_instagram_audience_demographics")
    op.execute("DROP VIEW vw_instagram_account_insights")
    op.execute("DROP VIEW vw_instagram_media_performance")
    with op.batch_alter_table("instagram_account_insights") as batch:
        batch.drop_constraint("uq_account_insights_period", type_="unique")
        batch.drop_column("reposts")
    with op.batch_alter_table("instagram_audience_demographics") as batch:
        batch.drop_constraint("uq_audience_daily_bucket", type_="unique")
    op.execute(f"CREATE VIEW vw_instagram_account_insights AS {ACCOUNT_VIEW}")
    sql = MEDIA_PERFORMANCE_VIEW.format(extra_columns="")
    op.execute(f"CREATE VIEW vw_instagram_media_performance AS {sql}")
