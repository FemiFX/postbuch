from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from postbuch.db.base import Base
from postbuch.models.enums import ProposalStatus
from postbuch.models.mixins import TimestampMixin


class CategoryProposal(TimestampMixin, Base):
    __tablename__ = "category_proposal"

    id: Mapped[int] = mapped_column(primary_key=True)
    proposed_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    proposal_reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ProposalStatus] = mapped_column(
        Enum(ProposalStatus, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        default=ProposalStatus.PENDING,
        nullable=False,
    )
    proposed_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    linked_category_id: Mapped[int | None] = mapped_column(ForeignKey("category.id"))

    linked_category = relationship("Category", back_populates="proposals")

