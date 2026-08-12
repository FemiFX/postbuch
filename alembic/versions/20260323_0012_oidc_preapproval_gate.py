"""oidc preapproval gate constraints

Revision ID: 20260323_0012
Revises: 20260321_0011
Create Date: 2026-03-23 17:30:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260323_0012"
down_revision: str | None = "20260321_0011"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE users SET email = lower(btrim(email)) WHERE email IS NOT NULL")
    op.execute(
        "UPDATE users SET email = 'legacy-user-' || id::text || '@local.invalid' WHERE email IS NULL OR btrim(email) = ''"
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT id, email, row_number() OVER (PARTITION BY email ORDER BY id) AS rn
            FROM users
            WHERE email IS NOT NULL
        )
        UPDATE users AS u
        SET email = 'legacy-dup-' || u.id::text || '@local.invalid'
        FROM ranked
        WHERE ranked.id = u.id AND ranked.rn > 1
        """
    )

    op.alter_column("users", "oidc_subject", existing_type=sa.String(length=255), nullable=True)
    op.alter_column("users", "email", existing_type=sa.String(length=255), nullable=False)
    op.drop_index("ix_users_email", table_name="users")
    op.create_index("uq_users_email", "users", ["email"], unique=True)

    op.alter_column("audit_log", "entity_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE audit_log SET entity_id = 0 WHERE entity_id IS NULL")
    op.alter_column("audit_log", "entity_id", existing_type=sa.Integer(), nullable=False)

    op.drop_index("uq_users_email", table_name="users")
    op.create_index("ix_users_email", "users", ["email"], unique=False)
    op.alter_column("users", "email", existing_type=sa.String(length=255), nullable=True)

    op.execute("UPDATE users SET oidc_subject = 'legacy:' || id::text WHERE oidc_subject IS NULL")
    op.alter_column("users", "oidc_subject", existing_type=sa.String(length=255), nullable=False)
