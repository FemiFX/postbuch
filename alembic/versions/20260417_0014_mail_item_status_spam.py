"""add spam mail item status

Revision ID: 20260417_0014
Revises: 20260323_0013
Create Date: 2026-04-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260417_0014"
down_revision: str | None = "20260323_0013"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

old_status_enum = sa.Enum(
    "neu",
    "in_bearbeitung",
    "wartet_aktion",
    "weitergeleitet",
    "beantwortet",
    "geschlossen",
    "fehler",
    name="mail_item_status_enum",
    native_enum=False,
)

new_status_enum = sa.Enum(
    "neu",
    "in_bearbeitung",
    "wartet_aktion",
    "weitergeleitet",
    "beantwortet",
    "geschlossen",
    "spam",
    "fehler",
    name="mail_item_status_enum",
    native_enum=False,
)


def upgrade() -> None:
    with op.batch_alter_table("mail_items") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=old_status_enum,
            type_=new_status_enum,
            existing_nullable=False,
        )


def downgrade() -> None:
    op.execute("UPDATE mail_items SET status = 'geschlossen' WHERE status = 'spam'")
    with op.batch_alter_table("mail_items") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=new_status_enum,
            type_=old_status_enum,
            existing_nullable=False,
        )
