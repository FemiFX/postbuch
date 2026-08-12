from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from postbuch.models.email_case import EmailCase
from postbuch.models.email_case_event import EmailCaseEvent
from postbuch.models.mail_item import MailItem


CASE_TOKEN_RE = re.compile(r"\b(CASE-\d{4}-\d{3,})\b", re.IGNORECASE)
REFERENCE_ID_RE = re.compile(r"<[^>]+>")
SUBJECT_PREFIX_RE = re.compile(r"^\s*(re|aw|fwd|fw)\s*:\s*", re.IGNORECASE)


def normalize_subject(subject: str | None) -> str:
    if not subject:
        return ""
    value = subject.strip()
    while True:
        updated = SUBJECT_PREFIX_RE.sub("", value).strip()
        if updated == value:
            break
        value = updated
    value = CASE_TOKEN_RE.sub("", value).strip()
    value = re.sub(r"\s+", " ", value)
    return value.lower()


def parse_reference_message_ids(references_raw: str | None) -> list[str]:
    if not references_raw:
        return []
    return REFERENCE_ID_RE.findall(references_raw)


def _new_case_key(now: datetime, case_id: int) -> str:
    return f"CASE-{now.year}-{case_id:04d}"


def resolve_case_for_mail_item(
    db: Session,
    *,
    subject: str | None,
    message_id_header: str | None,
    in_reply_to_message_id: str | None,
    references_raw: str | None,
    received_at: datetime | None,
) -> tuple[EmailCase, str, float, bool]:
    now = received_at or datetime.now(timezone.utc)
    normalized = normalize_subject(subject)

    token_match = CASE_TOKEN_RE.search(subject or "")
    if token_match:
        token = token_match.group(1).upper()
        by_token = db.scalar(select(EmailCase).where(EmailCase.public_case_key == token))
        if by_token is not None:
            return by_token, "case_token", 1.0, False

    if in_reply_to_message_id:
        parent = db.scalar(
            select(MailItem)
            .where(MailItem.message_id_header == in_reply_to_message_id, MailItem.case_id.is_not(None))
            .order_by(MailItem.id.desc())
        )
        if parent and parent.case_id:
            case = db.get(EmailCase, parent.case_id)
            if case is not None:
                return case, "in_reply_to", 0.98, False

    reference_ids = parse_reference_message_ids(references_raw)
    if reference_ids:
        parent = db.scalar(
            select(MailItem)
            .where(MailItem.message_id_header.in_(reference_ids), MailItem.case_id.is_not(None))
            .order_by(MailItem.id.desc())
        )
        if parent and parent.case_id:
            case = db.get(EmailCase, parent.case_id)
            if case is not None:
                return case, "references", 0.95, False

    if normalized:
        by_subject = db.scalar(
            select(EmailCase)
            .where(EmailCase.subject_canonical == normalized, EmailCase.is_closed.is_(False))
            .order_by(EmailCase.last_message_at.desc())
        )
        if by_subject is not None:
            return by_subject, "heuristic", 0.80, False

    case = EmailCase(
        public_case_key=None,
        subject_canonical=normalized or None,
        status="neu",
        last_message_at=now,
        last_incoming_at=now,
        message_count=0,
        is_closed=False,
    )
    db.add(case)
    db.flush()
    case.public_case_key = _new_case_key(now, case.id)
    return case, "new_case", 1.0, True


def attach_mail_item_to_case(
    db: Session,
    *,
    case: EmailCase,
    mail_item: MailItem,
    resolution_method: str,
    resolution_confidence: float,
    actor_type: str = "system",
) -> None:
    is_new_assignment = mail_item.case_id != case.id
    mail_item.case_id = case.id
    mail_item.resolution_method = resolution_method
    mail_item.resolution_confidence = resolution_confidence
    if case.assigned_user_id and mail_item.assigned_to_user_id is None:
        mail_item.assigned_to_user_id = case.assigned_user_id

    if is_new_assignment:
        case.message_count += 1
    message_time = mail_item.received_at or datetime.now(timezone.utc)
    case.last_message_at = message_time
    case.last_incoming_at = message_time

    db.add(
        EmailCaseEvent(
            case_id=case.id,
            message_id=mail_item.id,
            actor_user_id=None,
            actor_type=actor_type,
            event_type="message_attached",
            payload_json={
                "mail_item_id": mail_item.id,
                "resolution_method": resolution_method,
                "resolution_confidence": resolution_confidence,
                "message_id_header": mail_item.message_id_header,
            },
        )
    )
