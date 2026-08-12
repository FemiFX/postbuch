from datetime import date

from sqlalchemy import Boolean, Date, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from postbuch.db.base import Base
from postbuch.models.enums import Direction, MailboxProcessingMode
from postbuch.models.mixins import TimestampMixin


class Mailbox(TimestampMixin, Base):
    __tablename__ = "mailboxes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    direction: Mapped[Direction] = mapped_column(Enum(Direction, native_enum=False, values_callable=lambda x: [e.value for e in x]), nullable=False)
    imap_folder: Mapped[str] = mapped_column(String(255), nullable=False)
    processed_folder: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    processing_mode: Mapped[MailboxProcessingMode] = mapped_column(
        Enum(MailboxProcessingMode, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        default=MailboxProcessingMode.SCAN_IMPORT,
        nullable=False,
    )
    imap_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    imap_port: Mapped[int] = mapped_column(Integer, default=993, nullable=False)
    imap_use_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    imap_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    imap_password: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fetch_since: Mapped[date | None] = mapped_column(Date, nullable=True)
    sent_folder: Mapped[str | None] = mapped_column(String(255), nullable=True, default="Sent")

