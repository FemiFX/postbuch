from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from postbuch.db.base import Base
from postbuch.models.mixins import TimestampMixin


class ImportRun(TimestampMixin, Base):
    __tablename__ = "import_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    mailbox_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    messages_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    messages_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    messages_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    messages_skipped_duplicate: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

