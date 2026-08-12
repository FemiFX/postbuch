from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from postbuch.db.base import Base
from postbuch.models.enums import ProcessingStatus
from postbuch.models.mixins import TimestampMixin


class EmailMessage(TimestampMixin, Base):
    __tablename__ = "email_messages"
    __table_args__ = (UniqueConstraint("mailbox_name", "mailbox_uid", name="uq_email_mailbox_uid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("email_cases.id"), nullable=True, index=True)
    mailbox_name: Mapped[str] = mapped_column(String(100), nullable=False)
    mailbox_uid: Mapped[str] = mapped_column(String(100), nullable=False)
    message_id_header: Mapped[str | None] = mapped_column(Text, index=True)
    in_reply_to_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    references_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str | None] = mapped_column(Text)
    sender: Mapped[str | None] = mapped_column(Text)
    recipient: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        default=ProcessingStatus.FAILED,
        nullable=False,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    resolution_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_headers_json: Mapped[str | None] = mapped_column(Text)
