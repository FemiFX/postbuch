from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from postbuch.db.base import Base
from postbuch.models.enums import MailItemActionType, MailItemStatus
from postbuch.models.mixins import TimestampMixin


class MailItem(TimestampMixin, Base):
    __tablename__ = "mail_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("email_cases.id"), nullable=True, index=True)
    mailbox_id: Mapped[int] = mapped_column(ForeignKey("mailboxes.id"), nullable=False, index=True)
    message_id_header: Mapped[str | None] = mapped_column(Text, nullable=True)
    in_reply_to_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    references_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    mailbox_uid: Mapped[str] = mapped_column(String(100), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    sender: Mapped[str | None] = mapped_column(Text, nullable=True)
    recipient: Mapped[str | None] = mapped_column(Text, nullable=True)
    cc: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw_headers_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[MailItemStatus] = mapped_column(
        Enum(MailItemStatus, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        default=MailItemStatus.NEW,
        nullable=False,
        index=True,
    )
    category_id: Mapped[int | None] = mapped_column(ForeignKey("category.id"), nullable=True, index=True)
    assigned_to_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action_type: Mapped[MailItemActionType | None] = mapped_column(
        Enum(MailItemActionType, native_enum=False, values_callable=lambda x: [e.value for e in x]), nullable=True
    )
    action_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    forward_targets_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reply_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # IMAP writeback tracking
    imap_folder: Mapped[str | None] = mapped_column(String(255), nullable=True)
    imap_uidvalidity: Mapped[str | None] = mapped_column(String(50), nullable=True)
    imap_seen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    imap_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    attachments: Mapped[list["MailItemAttachment"]] = relationship(  # noqa: F821
        "MailItemAttachment", back_populates="mail_item", cascade="all, delete-orphan"
    )
    notes: Mapped[list["MailItemNote"]] = relationship(  # noqa: F821
        "MailItemNote",
        back_populates="mail_item",
        cascade="all, delete-orphan",
        order_by="MailItemNote.created_at.asc()",
    )

    __table_args__ = (
        Index("ix_mail_items_mailbox_uid", "mailbox_id", "mailbox_uid", unique=True),
    )
