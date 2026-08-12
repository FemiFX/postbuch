"""add forwarding_templates table

Revision ID: 20260318_0006
Revises: 20260318_0005
Create Date: 2026-03-18 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260318_0006"
down_revision: str | None = "20260318_0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forwarding_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "forwarding_route_id",
            sa.Integer(),
            sa.ForeignKey("forwarding_routes.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("subject_template", sa.String(), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("forwarding_templates")
