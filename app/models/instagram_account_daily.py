from datetime import date, datetime

from sqlalchemy import BigInteger, Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import ID, Base, TimestampMixin, UTCDateTime


class InstagramAccountDaily(TimestampMixin, Base):
    __tablename__ = "instagram_account_daily"
    __table_args__ = (UniqueConstraint("account_id", "snapshot_date"),)

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ID, ForeignKey("instagram_accounts.id"))
    snapshot_date: Mapped[date] = mapped_column(Date)
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime())
    followers_count: Mapped[int | None] = mapped_column(BigInteger)
    follows_count: Mapped[int | None] = mapped_column(BigInteger)
    media_count: Mapped[int | None] = mapped_column(BigInteger)
    followers_delta: Mapped[int | None] = mapped_column(BigInteger)
