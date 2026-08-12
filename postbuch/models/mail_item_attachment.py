from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from postbuch.db.base import Base
from postbuch.models.mixins import TimestampMixin


class MailItemAttachment(TimestampMixin, Base):
    __tablename__ = "mail_item_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    mail_item_id: Mapped[int] = mapped_column(ForeignKey("mail_items.id", ondelete="CASCADE"), nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_bucket: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    storage_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False, index=True)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    mail_item: Mapped["MailItem"] = relationship("MailItem", back_populates="attachments")  # noqa: F821
