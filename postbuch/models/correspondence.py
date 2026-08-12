from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from postbuch.db.base import Base
from postbuch.models.enums import CorrespondenceStatus, Direction, OCRStatus, SourceType
from postbuch.models.mixins import TimestampMixin


class Correspondence(TimestampMixin, Base):
    __tablename__ = "correspondence"

    id: Mapped[int] = mapped_column(primary_key=True)
    direction: Mapped[Direction] = mapped_column(Enum(Direction, native_enum=False, values_callable=lambda x: [e.value for e in x]), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[CorrespondenceStatus] = mapped_column(
        Enum(CorrespondenceStatus, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        default=CorrespondenceStatus.NEW,
        nullable=False,
        index=True,
    )
    category_id: Mapped[int | None] = mapped_column(ForeignKey("category.id"), index=True)
    completion_note: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    placement_location: Mapped[str | None] = mapped_column(Text)
    handoff_target: Mapped[str | None] = mapped_column(Text)
    notification_done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notification_channel: Mapped[str | None] = mapped_column(String(100))
    notified_party: Mapped[str | None] = mapped_column(Text)
    processing_note: Mapped[str | None] = mapped_column(Text)
    ocr_text: Mapped[str | None] = mapped_column(Text)
    ocr_status: Mapped[OCRStatus] = mapped_column(
        Enum(OCRStatus, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        default=OCRStatus.PENDING,
        nullable=False,
    )
    ocr_method: Mapped[str | None] = mapped_column(String(100))
    ocr_confidence: Mapped[int | None] = mapped_column(Integer)
    ocr_page_count: Mapped[int | None] = mapped_column(Integer)
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        default=SourceType.EMAIL_IMPORT,
        nullable=False,
    )
    source_email_message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    source_mailbox: Mapped[str | None] = mapped_column(String(100), index=True)
    source_email_from: Mapped[str | None] = mapped_column(String(255))
    source_email_to: Mapped[str | None] = mapped_column(String(255))
    source_email_subject: Mapped[str | None] = mapped_column(String(500))
    source_email_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_email_date_header_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duplicate_of_correspondence_id: Mapped[int | None] = mapped_column(ForeignKey("correspondence.id"))
    is_duplicate_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    category = relationship("Category")
    documents = relationship("Document", back_populates="correspondence", cascade="all, delete-orphan")
