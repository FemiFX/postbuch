"""Add sent_folder to mailboxes

Revision ID: 20260318_0009
Revises: 20260318_0008
Create Date: 2026-03-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260318_0009"
down_revision = "20260318_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mailboxes",
        sa.Column("sent_folder", sa.String(255), nullable=True, server_default="Sent"),
    )


def downgrade() -> None:
    op.drop_column("mailboxes", "sent_folder")
