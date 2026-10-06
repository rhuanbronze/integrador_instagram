"""Initial schema and Power BI views; this revision is deliberately self-contained."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
DT = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def pk():
    return sa.Column("id", ID, primary_key=True, autoincrement=True)


def timestamps():
    return [
        sa.Column("created_at", DT, nullable=False),
        sa.Column("updated_at", DT, nullable=False),
    ]


def counters(names):
    return [sa.Column(name, sa.BigInteger(), nullable=True) for name in names.split()]


VIEWS = {
    "vw_instagram_account_daily": """
        SELECT d.snapshot_date AS date, a.instagram_user_id, a.username,
               d.followers_count, d.followers_delta, d.follows_count, d.media_count
        FROM instagram_account_daily d JOIN instagram_accounts a ON a.id = d.account_id
    """,
    "vw_instagram_account_insights": """
        SELECT i.*, a.instagram_user_id, a.username
        FROM instagram_account_insights i JOIN instagram_accounts a ON a.id = i.account_id
    """,
    "vw_instagram_media": """
        SELECT account_id, instagram_media_id, published_at, media_type, media_product_type,
               caption, permalink, like_count, comments_count
        FROM instagram_media
    """,
    "vw_instagram_media_latest_insights": """
        SELECT media_id, views, reach, likes, comments, shares, saved, total_interactions,
               follows, profile_visits, avg_watch_time_ms, total_watch_time_ms, skip_rate,
               collected_at
        FROM (
            SELECT i.*, ROW_NUMBER() OVER (
                PARTITION BY media_id ORDER BY collected_at DESC, id DESC
            ) AS snapshot_rank FROM instagram_media_insights i
        ) ranked WHERE snapshot_rank = 1
    """,
    "vw_instagram_media_performance": """
        SELECT m.account_id, m.instagram_media_id, m.published_at, m.media_type,
               m.media_product_type, m.caption, m.permalink,
               i.views, i.reach, i.likes, i.comments, i.shares, i.saved, i.total_interactions,
               i.collected_at,
               100.0 * i.total_interactions / NULLIF(i.reach, 0) AS engagement_rate_reach,
               100.0 * i.shares / NULLIF(i.reach, 0) AS share_rate,
               100.0 * i.saved / NULLIF(i.reach, 0) AS save_rate
        FROM instagram_media m
        LEFT JOIN vw_instagram_media_latest_insights i ON i.media_id = m.id
    """,
}


def upgrade():
    op.create_table(
        "instagram_accounts",
        pk(),
        sa.Column("instagram_user_id", sa.String(50), nullable=False, unique=True),
        sa.Column("username", sa.String(255)),
        sa.Column("name", sa.String(255)),
        sa.Column("profile_picture_url", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        *timestamps(),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_table(
        "instagram_account_daily",
        pk(),
        sa.Column("account_id", ID, sa.ForeignKey("instagram_accounts.id"), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("collected_at", DT, nullable=False),
        *counters("followers_count follows_count media_count followers_delta"),
        *timestamps(),
        sa.UniqueConstraint("account_id", "snapshot_date"),
    )
    op.create_table(
        "instagram_account_insights",
        pk(),
        sa.Column("account_id", ID, sa.ForeignKey("instagram_accounts.id"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("collected_at", DT, nullable=False),
        *counters(
            "views reach accounts_engaged total_interactions likes comments shares saves "
            "follows unfollows profile_visits profile_links_taps"
        ),
        *timestamps(),
    )
    op.create_index(
        "ix_account_insights_period",
        "instagram_account_insights",
        ["account_id", "period_start", "period_end"],
    )
    op.create_table(
        "instagram_media",
        pk(),
        sa.Column("account_id", ID, sa.ForeignKey("instagram_accounts.id"), nullable=False),
        sa.Column("instagram_media_id", sa.String(50), nullable=False, unique=True),
        sa.Column("caption", sa.Text()),
        sa.Column("media_type", sa.String(50)),
        sa.Column("media_product_type", sa.String(50)),
        sa.Column("permalink", sa.Text()),
        sa.Column("thumbnail_url", sa.Text()),
        sa.Column("media_url", sa.Text()),
        sa.Column("published_at", DT, nullable=False),
        *counters("like_count comments_count"),
        sa.Column("first_seen_at", DT, nullable=False),
        sa.Column("last_seen_at", DT, nullable=False),
        *timestamps(),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_media_account_published", "instagram_media", ["account_id", "published_at"])
    op.create_table(
        "instagram_media_insights",
        pk(),
        sa.Column("media_id", ID, sa.ForeignKey("instagram_media.id"), nullable=False),
        sa.Column("collected_at", DT, nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        *counters(
            "views reach likes comments shares saved total_interactions follows "
            "profile_visits avg_watch_time_ms total_watch_time_ms"
        ),
        sa.Column("skip_rate", sa.Numeric(10, 4)),
        *timestamps(),
        sa.UniqueConstraint("media_id", "collected_at"),
    )
    op.create_table(
        "instagram_audience_demographics",
        pk(),
        sa.Column("account_id", ID, sa.ForeignKey("instagram_accounts.id"), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("audience_type", sa.String(50), nullable=False),
        sa.Column("breakdown_type", sa.String(50), nullable=False),
        sa.Column("breakdown_value", sa.String(255), nullable=False),
        sa.Column("metric_value", sa.BigInteger()),
        sa.Column("collected_at", DT, nullable=False),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "ix_audience_account_snapshot",
        "instagram_audience_demographics",
        ["account_id", "snapshot_date"],
    )
    op.create_table(
        "etl_runs",
        pk(),
        sa.Column("job_type", sa.String(50), nullable=False),
        sa.Column("started_at", DT, nullable=False),
        sa.Column("finished_at", DT),
        sa.Column("status", sa.String(30), nullable=False),
        *[
            sa.Column(name, sa.BigInteger(), nullable=False, server_default=sa.text("0"))
            for name in (
                "records_read",
                "records_inserted",
                "records_updated",
                "warnings_count",
                "errors_count",
            )
        ],
        sa.Column("error_message", sa.Text()),
    )
    op.create_index("ix_etl_runs_job_type", "etl_runs", ["job_type"])
    op.create_index("ix_etl_runs_status", "etl_runs", ["status"])
    for name, sql in VIEWS.items():
        op.execute(f"CREATE VIEW {name} AS {sql}")


def downgrade():
    for name in reversed(VIEWS):
        op.execute(f"DROP VIEW {name}")
    for name in (
        "etl_runs",
        "instagram_audience_demographics",
        "instagram_media_insights",
        "instagram_media",
        "instagram_account_insights",
        "instagram_account_daily",
        "instagram_accounts",
    ):
        op.drop_table(name)
