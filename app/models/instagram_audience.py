from datetime import date, datetime

from sqlalchemy import BigInteger, Date, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import ID, Base, UTCDateTime


class InstagramAudienceDemographics(Base):
    __tablename__ = "instagram_audience_demographics"
    __table_args__ = (
        Index("ix_audience_account_snapshot", "account_id", "snapshot_date"),
        UniqueConstraint(
            "account_id",
            "snapshot_date",
            "audience_type",
            "breakdown_type",
            "breakdown_value",
            name="uq_audience_daily_bucket",
        ),
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ID, ForeignKey("instagram_accounts.id"))
    snapshot_date: Mapped[date] = mapped_column(Date)
    audience_type: Mapped[str] = mapped_column(String(50))
    breakdown_type: Mapped[str] = mapped_column(String(50))
    breakdown_value: Mapped[str] = mapped_column(String(255))
    metric_value: Mapped[int | None] = mapped_column(BigInteger)
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime())
