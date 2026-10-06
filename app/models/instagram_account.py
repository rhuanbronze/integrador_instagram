from sqlalchemy import Boolean, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import ID, Base, TimestampMixin


class InstagramAccount(TimestampMixin, Base):
    __tablename__ = "instagram_accounts"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    instagram_user_id: Mapped[str] = mapped_column(String(50), unique=True)
    username: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(255))
    profile_picture_url: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
