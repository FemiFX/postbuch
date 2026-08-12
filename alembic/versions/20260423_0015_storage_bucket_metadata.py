"""add storage bucket metadata to stored files

Revision ID: 20260423_0015
Revises: 20260417_0014
Create Date: 2026-04-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260423_0015"
down_revision: str | None = "20260417_0014"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(sa.Column("storage_bucket", sa.String(length=255), nullable=False, server_default=""))
    with op.batch_alter_table("mail_item_attachments") as batch_op:
        batch_op.add_column(sa.Column("storage_bucket", sa.String(length=255), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("mail_item_attachments") as batch_op:
        batch_op.drop_column("storage_bucket")
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_column("storage_bucket")
