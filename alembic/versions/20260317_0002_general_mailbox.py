"""general mailbox triage (phase 1+2)

Revision ID: 20260317_0002
Revises: 20260317_0001
Create Date: 2026-03-17 13:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260317_0002"
down_revision: str | None = "20260317_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

processing_mode_enum = sa.Enum("scan_import", "general_triage", name="mailbox_processing_mode_enum", native_enum=False)
mail_item_status_enum = sa.Enum(
    "neu", "in_bearbeitung", "wartet_aktion", "weitergeleitet", "beantwortet", "geschlossen", "fehler",
    name="mail_item_status_enum",
    native_enum=False,
)
mail_item_action_type_enum = sa.Enum("forward", "reply", "none", name="mail_item_action_type_enum", native_enum=False)


def upgrade() -> None:
    # Phase 1: add processing_mode to mailboxes
    op.add_column(
        "mailboxes",
        sa.Column("processing_mode", processing_mode_enum, nullable=False, server_default="scan_import"),
    )

    # Phase 2: mail_items table
    op.create_table(
        "mail_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mailbox_id", sa.Integer(), sa.ForeignKey("mailboxes.id"), nullable=False),
        sa.Column("message_id_header", sa.String(length=500), nullable=True),
        sa.Column("mailbox_uid", sa.String(length=100), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("sender", sa.String(length=500), nullable=True),
        sa.Column("recipient", sa.String(length=1000), nullable=True),
        sa.Column("cc", sa.String(length=1000), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("has_attachments", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("raw_headers_json", sa.Text(), nullable=False),
        sa.Column("status", mail_item_status_enum, nullable=False, server_default="neu"),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("category.id"), nullable=True),
        sa.Column("assigned_to_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action_type", mail_item_action_type_enum, nullable=True),
        sa.Column("action_status", sa.String(length=100), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("forward_targets_json", sa.Text(), nullable=True),
        sa.Column("reply_subject", sa.String(length=500), nullable=True),
        sa.Column("reply_body", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index("ix_mail_items_mailbox_id", "mail_items", ["mailbox_id"])
    op.create_index("ix_mail_items_status", "mail_items", ["status"])
    op.create_index("ix_mail_items_category_id", "mail_items", ["category_id"])
    op.create_index("ix_mail_items_mailbox_uid", "mail_items", ["mailbox_id", "mailbox_uid"], unique=True)

    # Phase 2: mail_item_attachments table
    op.create_table(
        "mail_item_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mail_item_id", sa.Integer(), sa.ForeignKey("mail_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_filename", sa.String(length=500), nullable=False),
        sa.Column("stored_filename", sa.String(length=500), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False, unique=True),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index("ix_mail_item_attachments_mail_item_id", "mail_item_attachments", ["mail_item_id"])
    op.create_index("ix_mail_item_attachments_storage_key", "mail_item_attachments", ["storage_key"], unique=True)
    op.create_index("ix_mail_item_attachments_sha256_hash", "mail_item_attachments", ["sha256_hash"])


def downgrade() -> None:
    op.drop_table("mail_item_attachments")
    op.drop_table("mail_items")
    op.drop_column("mailboxes", "processing_mode")
