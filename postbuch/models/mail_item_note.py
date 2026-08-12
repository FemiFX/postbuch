from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from postbuch.db.base import Base
from postbuch.models.mixins import TimestampMixin


class MailItemNote(TimestampMixin, Base):
    __tablename__ = "mail_item_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    mail_item_id: Mapped[int] = mapped_column(
        ForeignKey("mail_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    mail_item: Mapped["MailItem"] = relationship("MailItem", back_populates="notes")  # noqa: F821
    author: Mapped["User | None"] = relationship("User")  # noqa: F821
