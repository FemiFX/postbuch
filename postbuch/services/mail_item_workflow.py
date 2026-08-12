from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from postbuch.models.audit_log import AuditLog
from postbuch.models.email_case import EmailCase
from postbuch.models.enums import MailItemActionType, MailItemStatus
from postbuch.models.mail_item import MailItem
from postbuch.models.mail_item_note import MailItemNote
from postbuch.services.audit import create_audit_entry

CASE_CLOSED_STATUSES = {MailItemStatus.CLOSED, MailItemStatus.SPAM}
WRITEBACK_STATUSES = {MailItemStatus.CLOSED, MailItemStatus.SPAM}


def list_mail_items_for_triage(
    db: Session,
    *,
    mailbox_id: int | None = None,
    status_filter: MailItemStatus | None = None,
    status_filters: list[MailItemStatus] | None = None,
    category_id: int | None = None,
    assigned_to_user_id: int | None = None,
    assigned_is_null: bool | None = None,
    query: str | None = None,
) -> list[MailItem]:
    stmt = (
        select(MailItem)
        .options(joinedload(MailItem.attachments))
        .order_by(MailItem.received_at.desc().nulls_last(), MailItem.created_at.desc())
    )
    if mailbox_id is not None:
        stmt = stmt.where(MailItem.mailbox_id == mailbox_id)
    if status_filter is not None:
        stmt = stmt.where(MailItem.status == status_filter)
    if status_filters:
        stmt = stmt.where(MailItem.status.in_(status_filters))
    if category_id is not None:
        stmt = stmt.where(MailItem.category_id == category_id)
    if assigned_to_user_id is not None:
        stmt = stmt.where(MailItem.assigned_to_user_id == assigned_to_user_id)
    elif assigned_is_null is True:
        stmt = stmt.where(MailItem.assigned_to_user_id.is_(None))
    if query:
        like = f"%{query}%"
        stmt = stmt.where(
            or_(
                MailItem.subject.ilike(like),
                MailItem.body_text.ilike(like),
                MailItem.sender.ilike(like),
            )
        )
    return list(db.scalars(stmt).unique())


def get_mail_item_timeline(db: Session, *, mail_item_id: int) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.entity_type == "mail_item", AuditLog.entity_id == mail_item_id)
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        )
    )


def list_mail_item_notes(db: Session, *, mail_item_id: int) -> list[MailItemNote]:
    return list(
        db.scalars(
            select(MailItemNote)
            .where(MailItemNote.mail_item_id == mail_item_id)
            .order_by(MailItemNote.created_at.asc(), MailItemNote.id.asc())
        )
    )


def add_mail_item_note(
    db: Session,
    *,
    mail_item: MailItem,
    author_user_id: int | None,
    body: str,
) -> MailItemNote:
    cleaned = (body or "").strip()
    if not cleaned:
        raise ValueError("Note body must not be empty.")
    note = MailItemNote(
        mail_item_id=mail_item.id,
        author_user_id=author_user_id,
        body=cleaned,
    )
    db.add(note)
    db.flush()
    create_audit_entry(
        db,
        entity_type="mail_item",
        entity_id=mail_item.id,
        action="note_added",
        actor_user_id=author_user_id,
        before_json=None,
        after_json={"note_id": note.id, "length": len(cleaned)},
    )
    return note


def _add_mail_item_event(
    db: Session,
    *,
    item: MailItem,
    action: str,
    actor_user_id: int | None,
    before_json: dict | None,
    after_json: dict | None,
) -> None:
    create_audit_entry(
        db,
        entity_type="mail_item",
        entity_id=item.id,
        action=action,
        actor_user_id=actor_user_id,
        before_json=before_json,
        after_json=after_json,
    )


def _mirror_case_state(db: Session, *, item: MailItem) -> None:
    if item.case_id is None:
        return
    case = db.get(EmailCase, item.case_id)
    if case is None:
        return
    case.assigned_user_id = item.assigned_to_user_id
    case.status = item.status.value
    case.is_closed = item.status in CASE_CLOSED_STATUSES
    case.category_id = item.category_id
    message_time = item.received_at or datetime.now(timezone.utc)
    case.last_message_at = message_time
    case.last_incoming_at = message_time


def _apply_status_transition(
    db: Session,
    *,
    item: MailItem,
    next_status: MailItemStatus,
    actor_user_id: int | None,
    perform_writeback: callable | None,
    reason: str | None = None,
) -> None:
    if item.status == next_status:
        return
    previous = item.status
    item.status = next_status
    if next_status in WRITEBACK_STATUSES:
        item.processed_at = datetime.now(timezone.utc)
        if perform_writeback is not None:
            perform_writeback(db, item)
    _add_mail_item_event(
        db,
        item=item,
        action="status_changed",
        actor_user_id=actor_user_id,
        before_json={"status": previous.value},
        after_json={"status": next_status.value, "reason": reason},
    )


def update_mail_item_from_patch(
    db: Session,
    *,
    item: MailItem,
    patch: dict[str, Any],
    actor_user_id: int | None,
    perform_writeback: callable | None = None,
) -> MailItem:
    if "assigned_to_user_id" in patch:
        new_assignee = patch["assigned_to_user_id"]
        if item.assigned_to_user_id != new_assignee:
            old_assignee = item.assigned_to_user_id
            item.assigned_to_user_id = new_assignee
            _add_mail_item_event(
                db,
                item=item,
                action="unassigned" if new_assignee is None else "assigned",
                actor_user_id=actor_user_id,
                before_json={"assigned_to_user_id": old_assignee},
                after_json={"assigned_to_user_id": new_assignee},
            )
            if new_assignee is not None and item.status == MailItemStatus.NEW:
                _apply_status_transition(
                    db,
                    item=item,
                    next_status=MailItemStatus.IN_PROGRESS,
                    actor_user_id=actor_user_id,
                    perform_writeback=perform_writeback,
                    reason="assignment_auto_progress",
                )

    if "category_id" in patch:
        new_category = patch["category_id"]
        if item.category_id != new_category:
            old_category = item.category_id
            item.category_id = new_category
            _add_mail_item_event(
                db,
                item=item,
                action="category_changed",
                actor_user_id=actor_user_id,
                before_json={"category_id": old_category},
                after_json={"category_id": new_category},
            )
            if new_category is not None and item.status == MailItemStatus.NEW:
                _apply_status_transition(
                    db,
                    item=item,
                    next_status=MailItemStatus.IN_PROGRESS,
                    actor_user_id=actor_user_id,
                    perform_writeback=perform_writeback,
                    reason="category_auto_progress",
                )

    if "status" in patch and patch["status"] is not None:
        _apply_status_transition(
            db,
            item=item,
            next_status=MailItemStatus(patch["status"]),
            actor_user_id=actor_user_id,
            perform_writeback=perform_writeback,
        )

    if "resolution_note" in patch:
        note = patch["resolution_note"]
        if item.resolution_note != note:
            before_note = item.resolution_note
            item.resolution_note = note
            _add_mail_item_event(
                db,
                item=item,
                action="note_saved",
                actor_user_id=actor_user_id,
                before_json={"resolution_note": before_note},
                after_json={"resolution_note": note},
            )

    passthrough_fields = {
        "action_type",
        "action_status",
        "reply_subject",
        "reply_body",
        "forward_targets_json",
    }
    for field in passthrough_fields:
        if field in patch:
            setattr(item, field, patch[field])

    _mirror_case_state(db, item=item)
    db.commit()
    db.refresh(item)
    return item


def close_mail_item(
    db: Session,
    *,
    item: MailItem,
    actor_user_id: int | None,
    perform_writeback: callable | None = None,
) -> MailItem:
    already_closed = item.status == MailItemStatus.CLOSED
    updated = update_mail_item_from_patch(
        db,
        item=item,
        patch={"status": MailItemStatus.CLOSED.value},
        actor_user_id=actor_user_id,
        perform_writeback=perform_writeback,
    )
    if not already_closed:
        _add_mail_item_event(
            db,
            item=updated,
            action="closed",
            actor_user_id=actor_user_id,
            before_json=None,
            after_json={"status": MailItemStatus.CLOSED.value},
        )
        db.commit()
        db.refresh(updated)
    return updated


def mark_mail_item_spam(
    db: Session,
    *,
    item: MailItem,
    actor_user_id: int | None,
    perform_writeback: callable | None = None,
) -> MailItem:
    already_spam = item.status == MailItemStatus.SPAM
    updated = update_mail_item_from_patch(
        db,
        item=item,
        patch={"status": MailItemStatus.SPAM.value},
        actor_user_id=actor_user_id,
        perform_writeback=perform_writeback,
    )
    if not already_spam:
        _add_mail_item_event(
            db,
            item=updated,
            action="spam_marked",
            actor_user_id=actor_user_id,
            before_json=None,
            after_json={"status": MailItemStatus.SPAM.value},
        )
        db.commit()
        db.refresh(updated)
    return updated


def record_forward_decision(
    db: Session,
    *,
    item: MailItem,
    target_json: dict[str, Any],
    after_status: MailItemStatus,
    note: str | None,
    actor_user_id: int | None,
    action_type: MailItemActionType = MailItemActionType.FORWARD,
    reply_subject: str | None = None,
    reply_body: str | None = None,
    event_action: str = "forwarded",
    perform_writeback: callable | None = None,
) -> MailItem:
    patch: dict[str, Any] = {
        "action_type": action_type,
        "forward_targets_json": json.dumps(target_json, ensure_ascii=False),
        "status": after_status.value,
    }
    if reply_subject is not None:
        patch["reply_subject"] = reply_subject
    if reply_body is not None:
        patch["reply_body"] = reply_body

    if note and note.strip():
        add_mail_item_note(db, mail_item=item, author_user_id=actor_user_id, body=note)

    updated = update_mail_item_from_patch(
        db,
        item=item,
        patch=patch,
        actor_user_id=actor_user_id,
        perform_writeback=perform_writeback,
    )
    _add_mail_item_event(
        db,
        item=updated,
        action=event_action,
        actor_user_id=actor_user_id,
        before_json=None,
        after_json={"target": target_json, "after_status": after_status.value},
    )
    db.commit()
    db.refresh(updated)
    return updated
