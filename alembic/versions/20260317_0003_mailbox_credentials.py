"""per-mailbox IMAP credentials

Revision ID: 20260317_0003
Revises: 20260317_0002
Create Date: 2026-03-17 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260317_0003"
down_revision: str | None = "20260317_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mailboxes", sa.Column("imap_host", sa.String(length=255), nullable=True))
    op.add_column("mailboxes", sa.Column("imap_port", sa.Integer(), nullable=False, server_default="993"))
    op.add_column("mailboxes", sa.Column("imap_use_ssl", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("mailboxes", sa.Column("imap_username", sa.String(length=255), nullable=True))
    op.add_column("mailboxes", sa.Column("imap_password", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("mailboxes", "imap_password")
    op.drop_column("mailboxes", "imap_username")
    op.drop_column("mailboxes", "imap_use_ssl")
    op.drop_column("mailboxes", "imap_port")
    op.drop_column("mailboxes", "imap_host")
