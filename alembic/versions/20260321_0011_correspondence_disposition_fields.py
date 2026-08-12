"""Add disposition fields to correspondence

Revision ID: 20260321_0011
Revises: 20260320_0010
Create Date: 2026-03-21
"""

from alembic import op
import sqlalchemy as sa

revision = "20260321_0011"
down_revision = "20260320_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("correspondence", sa.Column("placement_location", sa.Text(), nullable=True))
    op.add_column("correspondence", sa.Column("handoff_target", sa.Text(), nullable=True))
    op.add_column("correspondence", sa.Column("notification_done", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("correspondence", sa.Column("notification_channel", sa.String(100), nullable=True))
    op.add_column("correspondence", sa.Column("notified_party", sa.Text(), nullable=True))
    op.add_column("correspondence", sa.Column("processing_note", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("correspondence", "processing_note")
    op.drop_column("correspondence", "notified_party")
    op.drop_column("correspondence", "notification_channel")
    op.drop_column("correspondence", "notification_done")
    op.drop_column("correspondence", "handoff_target")
    op.drop_column("correspondence", "placement_location")
