from __future__ import annotations

import argparse

from sqlalchemy import select

from postbuch.db.session import SessionLocal
from postbuch.models.enums import Role
from postbuch.models.user import User
from postbuch.services.audit import create_audit_entry
from postbuch.services.users import create_user, normalize_email


def bootstrap_super_admin(*, email: str, display_name: str) -> tuple[User, bool]:
    normalized = normalize_email(email)
    if not normalized:
        raise ValueError("Email is required.")

    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == normalized))
        if existing is not None:
            before = {
                "display_name": existing.display_name,
                "role": existing.role.value,
                "is_active": existing.is_active,
            }
            existing.display_name = display_name.strip()
            existing.role = Role.SUPER_ADMIN
            existing.is_active = True
            create_audit_entry(
                db,
                entity_type="user",
                entity_id=existing.id,
                action="bootstrap_super_admin_updated",
                actor_user_id=None,
                before_json=before,
                after_json={
                    "display_name": existing.display_name,
                    "role": existing.role.value,
                    "is_active": existing.is_active,
                },
            )
            db.commit()
            db.refresh(existing)
            return existing, False

        user = create_user(
            db,
            email=normalized,
            display_name=display_name.strip(),
            role=Role.SUPER_ADMIN,
            is_active=True,
            actor_user_id=None,
        )
        return user, True


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed or reconcile an initial super_admin for OIDC preapproval mode.")
    parser.add_argument("--email", required=True, help="Email address that will be allowed to log in via OIDC.")
    parser.add_argument("--display-name", default="Initial Super Admin", help="Display name for the initial super admin.")
    args = parser.parse_args()

    user, created = bootstrap_super_admin(email=args.email, display_name=args.display_name)
    status = "created" if created else "updated"
    print(f"{status}: user_id={user.id} email={user.email} role={user.role.value} active={user.is_active}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
