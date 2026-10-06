from datetime import date, datetime

from sqlalchemy import BigInteger, Date, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import ID, Base, TimestampMixin, UTCDateTime


class InstagramAccountInsights(TimestampMixin, Base):
    __tablename__ = "instagram_account_insights"
    __table_args__ = (
        Index("ix_account_insights_period", "account_id", "period_start", "period_end"),
        UniqueConstraint(
            "account_id", "period_start", "period_end", name="uq_account_insights_period"
        ),
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ID, ForeignKey("instagram_accounts.id"))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime())
    views: Mapped[int | None] = mapped_column(BigInteger)
    reach: Mapped[int | None] = mapped_column(BigInteger)
    accounts_engaged: Mapped[int | None] = mapped_column(BigInteger)
    total_interactions: Mapped[int | None] = mapped_column(BigInteger)
    likes: Mapped[int | None] = mapped_column(BigInteger)
    comments: Mapped[int | None] = mapped_column(BigInteger)
    shares: Mapped[int | None] = mapped_column(BigInteger)
    saves: Mapped[int | None] = mapped_column(BigInteger)
    follows: Mapped[int | None] = mapped_column(BigInteger)
    unfollows: Mapped[int | None] = mapped_column(BigInteger)
    profile_visits: Mapped[int | None] = mapped_column(BigInteger)
    profile_links_taps: Mapped[int | None] = mapped_column(BigInteger)
    reposts: Mapped[int | None] = mapped_column(BigInteger)
