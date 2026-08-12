"""widen mail_items bulk string columns to Text

Revision ID: 20260513_0017
Revises: 20260512_0016
Create Date: 2026-05-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260513_0017"
down_revision: str | None = "20260512_0016"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


_COLUMNS_TO_WIDEN: list[tuple[str, int, bool]] = [
    # (column_name, previous_varchar_length, existing_nullable)
    ("subject", 500, False),
    ("sender", 500, True),
    ("recipient", 1000, True),
    ("cc", 1000, True),
    ("message_id_header", 500, True),
    ("in_reply_to_message_id", 500, True),
]


def upgrade() -> None:
    with op.batch_alter_table("mail_items") as batch_op:
        for column, _length, nullable in _COLUMNS_TO_WIDEN:
            batch_op.alter_column(column, type_=sa.Text(), existing_nullable=nullable)


def downgrade() -> None:
    with op.batch_alter_table("mail_items") as batch_op:
        for column, length, nullable in _COLUMNS_TO_WIDEN:
            batch_op.alter_column(column, type_=sa.String(length=length), existing_nullable=nullable)
