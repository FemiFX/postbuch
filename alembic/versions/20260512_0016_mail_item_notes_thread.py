"""mail_item_notes thread + backfill resolution_note

Revision ID: 20260512_0016
Revises: 20260423_0015
Create Date: 2026-05-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260512_0016"
down_revision: str | None = "20260423_0015"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mail_item_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "mail_item_id",
            sa.Integer(),
            sa.ForeignKey("mail_items.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("author_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.execute(
        """
        INSERT INTO mail_item_notes (mail_item_id, author_user_id, body, created_at, updated_at)
        SELECT id, NULL, resolution_note, COALESCE(updated_at, created_at, NOW()), COALESCE(updated_at, created_at, NOW())
        FROM mail_items
        WHERE resolution_note IS NOT NULL AND TRIM(resolution_note) <> ''
        """
    )


def downgrade() -> None:
    op.drop_table("mail_item_notes")
