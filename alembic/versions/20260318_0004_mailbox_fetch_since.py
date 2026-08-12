"""mailbox fetch_since date limit

Revision ID: 20260318_0004
Revises: 20260317_0003
Create Date: 2026-03-18 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260318_0004"
down_revision: str | None = "20260317_0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mailboxes", sa.Column("fetch_since", sa.Date(), nullable=True))
    # Seed existing mailboxes with yesterday's date so the first poll doesn't fetch all history
    op.execute("UPDATE mailboxes SET fetch_since = CURRENT_DATE - INTERVAL '1 day' WHERE fetch_since IS NULL")


def downgrade() -> None:
    op.drop_column("mailboxes", "fetch_since")
