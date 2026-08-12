from sqlalchemy import ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from postbuch.db.base import Base
from postbuch.models.mixins import TimestampMixin


class EmailCaseEvent(TimestampMixin, Base):
    __tablename__ = "email_case_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("email_cases.id"), nullable=False, index=True)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("mail_items.id"), nullable=True, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
