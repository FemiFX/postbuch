from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from postbuch.db.base import Base


class SmtpConfig(Base):
    """Single-row table (id=1) storing SMTP credentials editable via the admin UI.

    Takes precedence over env-based SMTP settings when smtp_host is set.
    """

    __tablename__ = "smtp_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    smtp_host: Mapped[str | None] = mapped_column(String, nullable=True)
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=587)
    smtp_username: Mapped[str | None] = mapped_column(String, nullable=True)
    smtp_password: Mapped[str | None] = mapped_column(String, nullable=True)
    smtp_from_address: Mapped[str | None] = mapped_column(String, nullable=True)
    smtp_use_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
