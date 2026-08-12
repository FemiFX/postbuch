from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from postbuch.db.base import Base
from postbuch.models.mixins import TimestampMixin


class Category(TimestampMixin, Base):
    __tablename__ = "category"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    proposals = relationship("CategoryProposal", back_populates="linked_category")

