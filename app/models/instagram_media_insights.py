from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import ID, Base, TimestampMixin, UTCDateTime


class InstagramMediaInsights(TimestampMixin, Base):
    __tablename__ = "instagram_media_insights"
    __table_args__ = (UniqueConstraint("media_id", "collected_at"),)

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    media_id: Mapped[int] = mapped_column(ID, ForeignKey("instagram_media.id"))
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime())
    snapshot_date: Mapped[date] = mapped_column(Date)
    views: Mapped[int | None] = mapped_column(BigInteger)
    reach: Mapped[int | None] = mapped_column(BigInteger)
    likes: Mapped[int | None] = mapped_column(BigInteger)
    comments: Mapped[int | None] = mapped_column(BigInteger)
    shares: Mapped[int | None] = mapped_column(BigInteger)
    saved: Mapped[int | None] = mapped_column(BigInteger)
    total_interactions: Mapped[int | None] = mapped_column(BigInteger)
    follows: Mapped[int | None] = mapped_column(BigInteger)
    profile_visits: Mapped[int | None] = mapped_column(BigInteger)
    avg_watch_time_ms: Mapped[int | None] = mapped_column(BigInteger)
    total_watch_time_ms: Mapped[int | None] = mapped_column(BigInteger)
    skip_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
