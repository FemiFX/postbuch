from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from postbuch.db.base import Base
from postbuch.models.mixins import TimestampMixin


class ForwardingRoute(Base, TimestampMixin):
    __tablename__ = "forwarding_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    target_email: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    templates: Mapped[list[ForwardingTemplate]] = relationship(  # type: ignore[name-defined]
        "ForwardingTemplate", back_populates="route", order_by="ForwardingTemplate.id", lazy="select"
    )
