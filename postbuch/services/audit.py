from __future__ import annotations

from sqlalchemy.orm import Session

from postbuch.models.audit_log import AuditLog
from postbuch.models.user import User


def create_audit_entry(
    db: Session,
    *,
    entity_type: str,
    entity_id: int | None,
    action: str,
    actor_user_id: int | None,
    before_json: dict | None,
    after_json: dict | None,
) -> AuditLog:
    entry = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_user_id=actor_user_id,
        before_json=before_json,
        after_json=after_json,
    )
    db.add(entry)
    return entry


def audit_login_success(db: Session, user: User) -> AuditLog:
    return create_audit_entry(
        db,
        entity_type="auth",
        entity_id=user.id,
        action="login_success",
        actor_user_id=user.id,
        before_json=None,
        after_json={"email": user.email},
    )


def audit_logout(db: Session, user: User) -> AuditLog:
    return create_audit_entry(
        db,
        entity_type="auth",
        entity_id=user.id,
        action="logout",
        actor_user_id=user.id,
        before_json=None,
        after_json={"email": user.email},
    )


def audit_login_failed(db: Session, *, email: str | None, reason: str) -> AuditLog:
    return create_audit_entry(
        db,
        entity_type="auth",
        entity_id=None,
        action="login_failed",
        actor_user_id=None,
        before_json=None,
        after_json={"email": email, "reason": reason},
    )
