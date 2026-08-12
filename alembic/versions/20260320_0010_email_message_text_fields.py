"""Widen email_messages sender/recipient/message_id/subject to TEXT

Revision ID: 20260320_0010
Revises: 20260318_0008
Create Date: 2026-03-20
"""

from alembic import op
import sqlalchemy as sa

revision = "20260320_0010"
down_revision = "20260318_0009"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("email_messages", "message_id_header",
                    existing_type=sa.String(255), type_=sa.Text(), existing_nullable=True)
    op.alter_column("email_messages", "subject",
                    existing_type=sa.String(500), type_=sa.Text(), existing_nullable=True)
    op.alter_column("email_messages", "sender",
                    existing_type=sa.String(255), type_=sa.Text(), existing_nullable=True)
    op.alter_column("email_messages", "recipient",
                    existing_type=sa.String(255), type_=sa.Text(), existing_nullable=True)


def downgrade():
    op.alter_column("email_messages", "recipient",
                    existing_type=sa.Text(), type_=sa.String(255), existing_nullable=True)
    op.alter_column("email_messages", "sender",
                    existing_type=sa.Text(), type_=sa.String(255), existing_nullable=True)
    op.alter_column("email_messages", "subject",
                    existing_type=sa.Text(), type_=sa.String(500), existing_nullable=True)
    op.alter_column("email_messages", "message_id_header",
                    existing_type=sa.Text(), type_=sa.String(255), existing_nullable=True)
