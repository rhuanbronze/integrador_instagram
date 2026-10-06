from datetime import datetime

from sqlalchemy import BigInteger, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import ID, Base, UTCDateTime


class ETLRun(Base):
    __tablename__ = "etl_runs"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(50), index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(30), index=True)
    records_read: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    records_inserted: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    records_updated: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    warnings_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    errors_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    error_message: Mapped[str | None] = mapped_column(Text)
