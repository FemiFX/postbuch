"""initial schema

Revision ID: 20260317_0001
Revises:
Create Date: 2026-03-17 12:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260317_0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


role_enum = sa.Enum("super_admin", "admin", "editor", "viewer", name="role_enum", native_enum=False)
direction_enum = sa.Enum("incoming", "outgoing", name="direction_enum", native_enum=False)
status_enum = sa.Enum("neu", "in_bearbeitung", "erledigt", name="correspondence_status_enum", native_enum=False)
source_type_enum = sa.Enum("email_import", "manual_upload", "manual_entry", name="source_type_enum", native_enum=False)
ocr_status_enum = sa.Enum("pending", "completed", "failed", "not_applicable", name="ocr_status_enum", native_enum=False)
processing_status_enum = sa.Enum(
    "processed", "failed", "skipped_duplicate", "invalid", name="processing_status_enum", native_enum=False
)
proposal_status_enum = sa.Enum("pending", "approved", "rejected", name="proposal_status_enum", native_enum=False)
document_role_enum = sa.Enum("source_scan", "supporting_document", name="document_role_enum", native_enum=False)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("oidc_subject", sa.String(length=255), nullable=False),
        sa.Column("oidc_issuer", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("role", role_enum, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("groups_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("oidc_subject"),
    )
    op.create_index("ix_users_oidc_subject", "users", ["oidc_subject"])
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "mailboxes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("direction", direction_enum, nullable=False),
        sa.Column("imap_folder", sa.String(length=255), nullable=False),
        sa.Column("processed_folder", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "category",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_category_slug", "category", ["slug"])

    op.create_table(
        "correspondence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("direction", direction_enum, nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("status", status_enum, nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("category.id")),
        sa.Column("completion_note", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("ocr_text", sa.Text(), nullable=True),
        sa.Column("ocr_status", ocr_status_enum, nullable=False),
        sa.Column("ocr_method", sa.String(length=100), nullable=True),
        sa.Column("ocr_confidence", sa.Integer(), nullable=True),
        sa.Column("ocr_page_count", sa.Integer(), nullable=True),
        sa.Column("source_type", source_type_enum, nullable=False),
        sa.Column("source_email_message_id", sa.String(length=255), nullable=True),
        sa.Column("source_mailbox", sa.String(length=100), nullable=True),
        sa.Column("source_email_from", sa.String(length=255), nullable=True),
        sa.Column("source_email_to", sa.String(length=255), nullable=True),
        sa.Column("source_email_subject", sa.String(length=500), nullable=True),
        sa.Column("source_email_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_email_date_header_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duplicate_of_correspondence_id", sa.Integer(), sa.ForeignKey("correspondence.id")),
        sa.Column("is_duplicate_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_correspondence_direction", "correspondence", ["direction"])
    op.create_index("ix_correspondence_title", "correspondence", ["title"])
    op.create_index("ix_correspondence_entry_date", "correspondence", ["entry_date"])
    op.create_index("ix_correspondence_status", "correspondence", ["status"])
    op.create_index("ix_correspondence_category_id", "correspondence", ["category_id"])
    op.create_index("ix_correspondence_source_email_message_id", "correspondence", ["source_email_message_id"])
    op.create_index("ix_correspondence_source_mailbox", "correspondence", ["source_mailbox"])
    op.create_index("ix_correspondence_is_duplicate_flag", "correspondence", ["is_duplicate_flag"])

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("correspondence_id", sa.Integer(), sa.ForeignKey("correspondence.id"), nullable=False),
        sa.Column("document_role", document_role_enum, nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256_hash", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("text_layer_present", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_documents_correspondence_id", "documents", ["correspondence_id"])
    op.create_index("ix_documents_sha256_hash", "documents", ["sha256_hash"])

    op.create_table(
        "email_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mailbox_name", sa.String(length=100), nullable=False),
        sa.Column("mailbox_uid", sa.String(length=100), nullable=False),
        sa.Column("message_id_header", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("sender", sa.String(length=255), nullable=True),
        sa.Column("recipient", sa.String(length=255), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_status", processing_status_enum, nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("raw_headers_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("mailbox_name", "mailbox_uid", name="uq_email_mailbox_uid"),
    )
    op.create_index("ix_email_messages_message_id_header", "email_messages", ["message_id_header"])
    op.create_index("ix_email_messages_processing_status", "email_messages", ["processing_status"])

    op.create_table(
        "category_proposal",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("proposed_name", sa.String(length=255), nullable=False),
        sa.Column("normalized_slug", sa.String(length=255), nullable=False),
        sa.Column("proposal_reason", sa.Text(), nullable=True),
        sa.Column("status", proposal_status_enum, nullable=False),
        sa.Column("proposed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("linked_category_id", sa.Integer(), sa.ForeignKey("category.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_category_proposal_normalized_slug", "category_proposal", ["normalized_slug"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_log_entity_type", "audit_log", ["entity_type"])
    op.create_index("ix_audit_log_entity_id", "audit_log", ["entity_id"])

    op.create_table(
        "import_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mailbox_name", sa.String(length=100), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("messages_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("messages_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("messages_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("messages_skipped_duplicate", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_import_runs_mailbox_name", "import_runs", ["mailbox_name"])
    op.create_index("ix_import_runs_status", "import_runs", ["status"])

    op.execute(
        "CREATE INDEX ix_correspondence_search ON correspondence USING GIN (to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(ocr_text, '')))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_correspondence_search")
    op.drop_index("ix_import_runs_status", table_name="import_runs")
    op.drop_index("ix_import_runs_mailbox_name", table_name="import_runs")
    op.drop_table("import_runs")
    op.drop_index("ix_audit_log_entity_id", table_name="audit_log")
    op.drop_index("ix_audit_log_entity_type", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_category_proposal_normalized_slug", table_name="category_proposal")
    op.drop_table("category_proposal")
    op.drop_index("ix_email_messages_processing_status", table_name="email_messages")
    op.drop_index("ix_email_messages_message_id_header", table_name="email_messages")
    op.drop_table("email_messages")
    op.drop_index("ix_documents_sha256_hash", table_name="documents")
    op.drop_index("ix_documents_correspondence_id", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_correspondence_is_duplicate_flag", table_name="correspondence")
    op.drop_index("ix_correspondence_source_mailbox", table_name="correspondence")
    op.drop_index("ix_correspondence_source_email_message_id", table_name="correspondence")
    op.drop_index("ix_correspondence_category_id", table_name="correspondence")
    op.drop_index("ix_correspondence_status", table_name="correspondence")
    op.drop_index("ix_correspondence_entry_date", table_name="correspondence")
    op.drop_index("ix_correspondence_title", table_name="correspondence")
    op.drop_index("ix_correspondence_direction", table_name="correspondence")
    op.drop_table("correspondence")
    op.drop_index("ix_category_slug", table_name="category")
    op.drop_table("category")
    op.drop_table("mailboxes")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_oidc_subject", table_name="users")
    op.drop_table("users")
