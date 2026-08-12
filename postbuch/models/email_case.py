from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from postbuch.db.base import Base
from postbuch.models.mixins import TimestampMixin


class EmailCase(TimestampMixin, Base):
    __tablename__ = "email_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_case_key: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    subject_canonical: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="neu")
    category_id: Mapped[int | None] = mapped_column(ForeignKey("category.id"), nullable=True, index=True)
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_from_message_id: Mapped[int | None] = mapped_column(ForeignKey("mail_items.id"), nullable=True)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_incoming_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_outgoing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    waiting_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
