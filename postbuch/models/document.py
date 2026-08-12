from sqlalchemy import BigInteger, Boolean, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from postbuch.db.base import Base
from postbuch.models.enums import DocumentRole
from postbuch.models.mixins import TimestampMixin


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    correspondence_id: Mapped[int] = mapped_column(ForeignKey("correspondence.id"), nullable=False, index=True)
    document_role: Mapped[DocumentRole] = mapped_column(
        Enum(DocumentRole, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        default=DocumentRole.SOURCE_SCAN,
        nullable=False,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_bucket: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    page_count: Mapped[int | None] = mapped_column()
    text_layer_present: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    correspondence = relationship("Correspondence", back_populates="documents")
