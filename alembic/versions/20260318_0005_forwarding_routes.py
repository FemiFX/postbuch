"""add forwarding_routes table

Revision ID: 20260318_0005
Revises: 20260318_0004
Create Date: 2026-03-18 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260318_0005"
down_revision: str | None = "20260318_0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forwarding_routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("target_email", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Seed default departments
    op.execute("""
        INSERT INTO forwarding_routes (name, description, sort_order, is_active, created_at, updated_at)
        VALUES
            ('Beratung',                  'Beratungsteam',                  0, true, now(), now()),
            ('Buchhaltung',               'Buchhaltung & Finanzen',         1, true, now(), now()),
            ('Personal',                  'Personalwesen & HR',             2, true, now(), now()),
            ('Geschäftsführung',          'Geschäftsführung',               3, true, now(), now()),
            ('Veranstaltungskoordination','Veranstaltungskoordination',     4, true, now(), now()),
            ('Archiv',                    'Archiv & Dokumentation',         5, true, now(), now())
    """)


def downgrade() -> None:
    op.drop_table("forwarding_routes")
