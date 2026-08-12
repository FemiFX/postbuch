"""Add IMAP writeback tracking columns to mail_items

Revision ID: 20260318_0008
Revises: 20260318_0007
Create Date: 2026-03-18
"""

import sqlalchemy as sa
from alembic import op

revision = "20260318_0008"
down_revision = "20260318_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mail_items", sa.Column("imap_folder", sa.String(255), nullable=True))
    op.add_column("mail_items", sa.Column("imap_uidvalidity", sa.String(50), nullable=True))
    op.add_column("mail_items", sa.Column("imap_seen", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("mail_items", sa.Column("imap_processed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("mail_items", "imap_processed_at")
    op.drop_column("mail_items", "imap_seen")
    op.drop_column("mail_items", "imap_uidvalidity")
    op.drop_column("mail_items", "imap_folder")
