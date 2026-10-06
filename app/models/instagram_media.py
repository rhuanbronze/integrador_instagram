from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import ID, Base, TimestampMixin, UTCDateTime


class InstagramMedia(TimestampMixin, Base):
    __tablename__ = "instagram_media"
    __table_args__ = (Index("ix_media_account_published", "account_id", "published_at"),)

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ID, ForeignKey("instagram_accounts.id"))
    instagram_media_id: Mapped[str] = mapped_column(String(50), unique=True)
    caption: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(String(50))
    media_product_type: Mapped[str | None] = mapped_column(String(50))
    permalink: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    media_url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime())
    like_count: Mapped[int | None] = mapped_column(BigInteger)
    comments_count: Mapped[int | None] = mapped_column(BigInteger)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime())
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime())
