from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from postbuch.db.base import Base
from postbuch.models.mixins import TimestampMixin


class ForwardingTemplate(Base, TimestampMixin):
    __tablename__ = "forwarding_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    forwarding_route_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("forwarding_routes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    subject_template: Mapped[str] = mapped_column(String, nullable=False)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    route: Mapped["ForwardingRoute"] = relationship("ForwardingRoute", back_populates="templates")  # type: ignore[name-defined]
