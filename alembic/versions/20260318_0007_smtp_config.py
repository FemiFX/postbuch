"""Add smtp_config table for DB-editable SMTP settings

Revision ID: 20260318_0007
Revises: 20260318_0006
Create Date: 2026-03-18
"""

import sqlalchemy as sa
from alembic import op

revision = "20260318_0007"
down_revision = "20260318_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "smtp_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("smtp_host", sa.String(), nullable=True),
        sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="587"),
        sa.Column("smtp_username", sa.String(), nullable=True),
        sa.Column("smtp_password", sa.String(), nullable=True),
        sa.Column("smtp_from_address", sa.String(), nullable=True),
        sa.Column("smtp_use_tls", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_table("smtp_config")
