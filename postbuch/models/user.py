from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from postbuch.db.base import Base
from postbuch.models.enums import Role
from postbuch.models.mixins import TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    oidc_subject: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    oidc_issuer: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, values_callable=lambda x: [e.value for e in x]), default=Role.VIEWER, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    groups_json: Mapped[str | None] = mapped_column(Text)

    created_correspondence = relationship("Correspondence", foreign_keys="Correspondence.created_by_user_id")
    updated_correspondence = relationship("Correspondence", foreign_keys="Correspondence.updated_by_user_id")
