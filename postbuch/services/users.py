from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from postbuch.models.enums import Role
from postbuch.models.user import User
from postbuch.services.audit import create_audit_entry


class OIDCLoginError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


@dataclass
class OIDCUserInfo:
    subject: str | None
    issuer: str | None
    email: str | None
    display_name: str


def normalize_email(email: str | None) -> str | None:
    if email is None:
        return None
    return email.strip().lower()


def create_user(
    db: Session,
    *,
    email: str,
    display_name: str,
    role: Role,
    is_active: bool,
    actor_user_id: int | None,
) -> User:
    normalized = normalize_email(email)
    if not normalized:
        raise ValueError("Email is required.")

    existing = db.scalar(select(User).where(User.email == normalized))
    if existing is not None:
        raise ValueError("User with this email already exists.")

    user = User(
        email=normalized,
        display_name=display_name.strip(),
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.flush()
    create_audit_entry(
        db,
        entity_type="user",
        entity_id=user.id,
        action="created",
        actor_user_id=actor_user_id,
        before_json=None,
        after_json={"email": user.email, "role": user.role.value, "is_active": user.is_active},
    )
    db.commit()
    db.refresh(user)
    return user


def provision_oidc_preapproved_user(db: Session, *, oidc: OIDCUserInfo) -> User:
    email = normalize_email(oidc.email)
    if not oidc.subject:
        raise OIDCLoginError("OIDC response missing subject.")
    if not email:
        create_audit_entry(
            db,
            entity_type="auth",
            entity_id=None,
            action="oidc_denied_missing_email",
            actor_user_id=None,
            before_json=None,
            after_json={"subject": oidc.subject, "issuer": oidc.issuer},
        )
        db.commit()
        raise OIDCLoginError("OIDC response missing email.")

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        create_audit_entry(
            db,
            entity_type="auth",
            entity_id=None,
            action="oidc_denied_not_preapproved",
            actor_user_id=None,
            before_json=None,
            after_json={"email": email, "subject": oidc.subject, "issuer": oidc.issuer},
        )
        db.commit()
        raise OIDCLoginError("User is not pre-approved for OIDC login.")

    if not user.is_active:
        create_audit_entry(
            db,
            entity_type="auth",
            entity_id=user.id,
            action="oidc_denied_inactive",
            actor_user_id=user.id,
            before_json=None,
            after_json={"email": email, "subject": oidc.subject},
        )
        db.commit()
        raise OIDCLoginError("User is inactive.")

    if user.oidc_subject is None:
        user.oidc_subject = oidc.subject
        user.oidc_issuer = oidc.issuer
        create_audit_entry(
            db,
            entity_type="user",
            entity_id=user.id,
            action="oidc_bound",
            actor_user_id=user.id,
            before_json=None,
            after_json={"oidc_subject": oidc.subject, "oidc_issuer": oidc.issuer},
        )
    else:
        if user.oidc_subject != oidc.subject:
            create_audit_entry(
                db,
                entity_type="auth",
                entity_id=user.id,
                action="oidc_denied_subject_mismatch",
                actor_user_id=user.id,
                before_json={"expected_subject": user.oidc_subject},
                after_json={"actual_subject": oidc.subject},
            )
            db.commit()
            raise OIDCLoginError("OIDC subject mismatch.")
        if user.oidc_issuer and oidc.issuer and user.oidc_issuer != oidc.issuer:
            create_audit_entry(
                db,
                entity_type="auth",
                entity_id=user.id,
                action="oidc_denied_issuer_mismatch",
                actor_user_id=user.id,
                before_json={"expected_issuer": user.oidc_issuer},
                after_json={"actual_issuer": oidc.issuer},
            )
            db.commit()
            raise OIDCLoginError("OIDC issuer mismatch.")

    user.display_name = oidc.display_name
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user


def provision_dev_user(
    db: Session,
    *,
    email: str | None,
    display_name: str,
    role: Role,
) -> User:
    email = normalize_email(email)
    subject_key = email or display_name
    oidc_subject = f"dev:{subject_key.strip().lower()}"
    user = db.scalar(select(User).where(User.oidc_subject == oidc_subject))
    effective_email = email or f"{oidc_subject}@local.dev"

    # Fall back to an email lookup and adopt the existing account. Users created
    # any other way — `bootstrap_super_admin`, a demo seed, a prior real OIDC
    # login — have no `dev:` subject, so matching on subject alone misses them
    # and the insert below then violates the unique constraint on users.email.
    if user is None:
        user = db.scalar(select(User).where(User.email == effective_email))
        if user is not None:
            user.oidc_subject = oidc_subject

    if user is None:
        user = User(
            oidc_subject=oidc_subject,
            display_name=display_name,
            email=effective_email,
            oidc_issuer="dev-local",
            role=role,
            last_login_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.flush()
        create_audit_entry(
            db,
            entity_type="user",
            entity_id=user.id,
            action="dev_provisioned",
            actor_user_id=user.id,
            before_json=None,
            after_json={"email": user.email, "role": role.value},
        )
    else:
        user.display_name = display_name
        user.email = effective_email
        user.oidc_issuer = "dev-local"
        user.role = role
        user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user


def update_user_role(db: Session, *, actor: User, target: User, role: Role) -> User:
    before = {"role": target.role}
    target.role = role
    create_audit_entry(
        db,
        entity_type="user",
        entity_id=target.id,
        action="role_changed",
        actor_user_id=actor.id,
        before_json=before,
        after_json={"role": target.role},
    )
    db.commit()
    db.refresh(target)
    return target


def update_user(
    db: Session,
    *,
    actor: User,
    target: User,
    display_name: str,
    role: Role,
    is_active: bool,
) -> User:
    cleaned_name = display_name.strip()
    if not cleaned_name:
        raise ValueError("Display name is required.")

    before = {"display_name": target.display_name, "role": target.role, "is_active": target.is_active}
    target.display_name = cleaned_name
    target.role = role
    target.is_active = is_active
    create_audit_entry(
        db,
        entity_type="user",
        entity_id=target.id,
        action="updated",
        actor_user_id=actor.id,
        before_json=before,
        after_json={"display_name": target.display_name, "role": target.role, "is_active": target.is_active},
    )
    db.commit()
    db.refresh(target)
    return target


def update_user_active(db: Session, *, actor: User, target: User, is_active: bool) -> User:
    before = {"is_active": target.is_active}
    target.is_active = is_active
    create_audit_entry(
        db,
        entity_type="user",
        entity_id=target.id,
        action="active_changed",
        actor_user_id=actor.id,
        before_json=before,
        after_json={"is_active": target.is_active},
    )
    db.commit()
    db.refresh(target)
    return target
