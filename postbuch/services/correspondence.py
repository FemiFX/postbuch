from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, joinedload

from postbuch.models.audit_log import AuditLog
from postbuch.models.category import Category
from postbuch.models.correspondence import Correspondence
from postbuch.models.document import Document
from postbuch.models.enums import CorrespondenceStatus, Direction, MailItemStatus, OCRStatus, Role, SourceType
from postbuch.models.mail_item import MailItem
from postbuch.models.user import User
from postbuch.schemas.correspondence import (
    CorrespondenceCreate,
    CorrespondenceDirectionUpdate,
    CorrespondenceFilter,
    CorrespondenceStatusUpdate,
    CorrespondenceUpdate,
)
from postbuch.services.audit import create_audit_entry


IMMUTABLE_SOURCE_FIELDS = {
    "source_email_message_id",
    "source_mailbox",
    "source_email_from",
    "source_email_to",
    "source_email_subject",
    "source_email_received_at",
    "source_email_date_header_at",
    "source_type",
}


def _ensure_editable(user: User) -> None:
    if user.role not in {Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR}:
        raise PermissionError("User may not edit correspondence.")


def _validate_done_state(
    status: CorrespondenceStatus,
    *,
    category_id: int | None = None,
    placement_location: str | None = None,
    handoff_target: str | None = None,
    processing_note: str | None = None,
) -> None:
    if status != CorrespondenceStatus.DONE:
        return
    if not category_id:
        raise ValueError("Eine Kategorie ist erforderlich, um die Korrespondenz als erledigt zu markieren.")
    has_disposition = any([
        (placement_location or "").strip(),
        (handoff_target or "").strip(),
        (processing_note or "").strip(),
    ])
    if not has_disposition:
        raise ValueError("Bitte mindestens ein Dispositionsfeld ausfüllen (Ablageort, Weitergegeben an oder Bearbeitungsvermerk).")


def _ensure_category_exists(db: Session, category_id: int | None) -> None:
    if category_id is None:
        return
    category = db.get(Category, category_id)
    if category is None or not category.is_active:
        raise ValueError("Only active confirmed categories may be assigned.")


def list_correspondence(db: Session, filters: CorrespondenceFilter) -> list[Correspondence]:
    stmt: Select[tuple[Correspondence]] = (
        select(Correspondence)
        .options(joinedload(Correspondence.category))
        .order_by(Correspondence.entry_date.desc(), Correspondence.created_at.desc())
    )
    if filters.direction:
        stmt = stmt.where(Correspondence.direction == filters.direction)
    if filters.status:
        stmt = stmt.where(Correspondence.status == filters.status)
    if filters.category_id:
        stmt = stmt.where(Correspondence.category_id == filters.category_id)
    if filters.source_mailbox:
        stmt = stmt.where(Correspondence.source_mailbox == filters.source_mailbox)
    if filters.date_from:
        stmt = stmt.where(Correspondence.entry_date >= filters.date_from)
    if filters.date_to:
        stmt = stmt.where(Correspondence.entry_date <= filters.date_to)
    if filters.query:
        query = filters.query.strip()
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            search_vector = func.to_tsvector(
                "simple",
                func.coalesce(Correspondence.title, "") + " " + func.coalesce(Correspondence.ocr_text, ""),
            )
            stmt = stmt.where(
                or_(
                    search_vector.op("@@")(func.plainto_tsquery("simple", query)),
                    Correspondence.source_email_from.ilike(f"%{query}%"),
                    Correspondence.source_email_subject.ilike(f"%{query}%"),
                )
            )
        else:
            stmt = stmt.where(
                or_(
                    Correspondence.title.ilike(f"%{query}%"),
                    Correspondence.ocr_text.ilike(f"%{query}%"),
                    Correspondence.source_email_from.ilike(f"%{query}%"),
                    Correspondence.source_email_subject.ilike(f"%{query}%"),
                )
            )
    return list(db.scalars(stmt).unique())


def create_manual_correspondence(
    db: Session,
    *,
    current_user: User,
    payload: CorrespondenceCreate,
    stored_document: Mapping[str, object] | None = None,
) -> Correspondence:
    _ensure_editable(current_user)
    _ensure_category_exists(db, payload.category_id)
    correspondence = Correspondence(
        direction=payload.direction,
        title=payload.title.strip(),
        entry_date=payload.entry_date,
        status=CorrespondenceStatus.NEW,
        category_id=payload.category_id,
        completion_note=payload.completion_note,
        notes=payload.notes,
        source_type=payload.source_type,
        ocr_status=OCRStatus.NOT_APPLICABLE,
        created_by_user_id=current_user.id,
        updated_by_user_id=current_user.id,
    )
    db.add(correspondence)
    db.flush()
    if stored_document:
        db.add(
            Document(
                correspondence_id=correspondence.id,
                original_filename=str(stored_document["original_filename"]),
                stored_filename=str(stored_document["stored_filename"]),
                storage_bucket=str(stored_document["storage_bucket"]),
                storage_key=str(stored_document["storage_key"]),
                mime_type=str(stored_document["mime_type"]),
                file_size_bytes=int(stored_document["file_size_bytes"]),
                sha256_hash=str(stored_document["sha256_hash"]),
                text_layer_present=False,
            )
        )
    create_audit_entry(
        db,
        entity_type="correspondence",
        entity_id=correspondence.id,
        action="created",
        actor_user_id=current_user.id,
        before_json=None,
        after_json={"title": correspondence.title, "direction": correspondence.direction},
    )
    db.commit()
    db.refresh(correspondence)
    return correspondence


def update_correspondence(db: Session, *, correspondence: Correspondence, current_user: User, payload: CorrespondenceUpdate) -> Correspondence:
    _ensure_editable(current_user)
    _ensure_category_exists(db, payload.category_id)
    _validate_done_state(
        payload.status,
        category_id=payload.category_id,
        placement_location=payload.placement_location,
        handoff_target=payload.handoff_target,
        processing_note=payload.processing_note,
    )
    before = serialize_correspondence(correspondence)
    correspondence.title = payload.title.strip()
    correspondence.entry_date = payload.entry_date
    correspondence.status = payload.status
    correspondence.category_id = payload.category_id
    correspondence.completion_note = payload.completion_note
    correspondence.notes = payload.notes
    correspondence.placement_location = payload.placement_location
    correspondence.handoff_target = payload.handoff_target
    correspondence.notification_done = payload.notification_done
    correspondence.notification_channel = payload.notification_channel
    correspondence.notified_party = payload.notified_party
    correspondence.processing_note = payload.processing_note
    correspondence.updated_by_user_id = current_user.id
    create_audit_entry(
        db,
        entity_type="correspondence",
        entity_id=correspondence.id,
        action="updated",
        actor_user_id=current_user.id,
        before_json=before,
        after_json=serialize_correspondence(correspondence),
    )
    db.commit()
    db.refresh(correspondence)
    return correspondence


def transition_status(db: Session, *, correspondence: Correspondence, current_user: User, payload: CorrespondenceStatusUpdate) -> Correspondence:
    _ensure_editable(current_user)
    _validate_done_state(
        payload.status,
        category_id=correspondence.category_id,
        placement_location=correspondence.placement_location,
        handoff_target=correspondence.handoff_target,
        processing_note=correspondence.processing_note,
    )
    before = {"status": correspondence.status, "completion_note": correspondence.completion_note}
    correspondence.status = payload.status
    correspondence.completion_note = payload.completion_note
    correspondence.updated_by_user_id = current_user.id
    create_audit_entry(
        db,
        entity_type="correspondence",
        entity_id=correspondence.id,
        action="status_changed",
        actor_user_id=current_user.id,
        before_json=before,
        after_json={"status": correspondence.status, "completion_note": correspondence.completion_note},
    )
    db.commit()
    db.refresh(correspondence)
    return correspondence


def move_direction(
    db: Session,
    *,
    correspondence: Correspondence,
    current_user: User,
    payload: CorrespondenceDirectionUpdate,
) -> Correspondence:
    _ensure_editable(current_user)
    if correspondence.direction == payload.direction:
        return correspondence

    before = {"direction": correspondence.direction}
    correspondence.direction = payload.direction
    correspondence.updated_by_user_id = current_user.id
    create_audit_entry(
        db,
        entity_type="correspondence",
        entity_id=correspondence.id,
        action="direction_changed",
        actor_user_id=current_user.id,
        before_json=before,
        after_json={"direction": correspondence.direction},
    )
    db.commit()
    db.refresh(correspondence)
    return correspondence


def dashboard_counts(db: Session) -> dict[str, int]:
    def count_where(*conditions: object) -> int:
        stmt = select(func.count(Correspondence.id))
        for condition in conditions:
            stmt = stmt.where(condition)
        return int(db.scalar(stmt) or 0)

    def count_mail_where(*conditions: object) -> int:
        stmt = select(func.count(MailItem.id))
        for condition in conditions:
            stmt = stmt.where(condition)
        return int(db.scalar(stmt) or 0)

    correspondence_new = count_where(Correspondence.status == CorrespondenceStatus.NEW)
    mail_new = count_mail_where(MailItem.status == MailItemStatus.NEW)

    return {
        "new": correspondence_new + mail_new,
        "in_progress": count_where(Correspondence.status == CorrespondenceStatus.IN_PROGRESS)
        + count_mail_where(MailItem.status == MailItemStatus.IN_PROGRESS),
        "incoming": count_where(Correspondence.direction == Direction.INCOMING) + count_mail_where(),
        "outgoing": count_where(Correspondence.direction == Direction.OUTGOING),
        "duplicates": count_where(Correspondence.is_duplicate_flag.is_(True)),
    }


def count_assigned_items(db: Session, user_id: int, *, active_only: bool = True) -> int:
    """Return count of MailItems assigned to a user.

    *active_only* excludes CLOSED, SPAM, and ERROR statuses.
    """
    stmt = select(func.count(MailItem.id)).where(
        MailItem.assigned_to_user_id == user_id
    )
    if active_only:
        stmt = stmt.where(
            MailItem.status.not_in([
                MailItemStatus.CLOSED,
                MailItemStatus.SPAM,
                MailItemStatus.ERROR,
            ])
        )
    return int(db.scalar(stmt) or 0)


def list_audit_entries(db: Session, correspondence_id: int) -> list[AuditLog]:
    stmt = select(AuditLog).where(AuditLog.entity_type == "correspondence", AuditLog.entity_id == correspondence_id).order_by(AuditLog.created_at.desc())
    return list(db.scalars(stmt))


def serialize_correspondence(correspondence: Correspondence) -> dict[str, object]:
    return {
        "id": correspondence.id,
        "direction": correspondence.direction,
        "title": correspondence.title,
        "entry_date": correspondence.entry_date.isoformat() if isinstance(correspondence.entry_date, date) else None,
        "status": correspondence.status,
        "category_id": correspondence.category_id,
        "completion_note": correspondence.completion_note,
        "notes": correspondence.notes,
    }
