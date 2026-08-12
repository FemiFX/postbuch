"""email case/thread foundation for triage

Revision ID: 20260323_0013
Revises: 20260323_0012
Create Date: 2026-03-23 20:30:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260323_0013"
down_revision: str | None = "20260323_0012"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_case_key", sa.String(length=64), nullable=True),
        sa.Column("subject_canonical", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="neu"),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("category.id"), nullable=True),
        sa.Column("assigned_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_from_message_id", sa.Integer(), sa.ForeignKey("mail_items.id"), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_incoming_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outgoing_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("waiting_reason", sa.String(length=255), nullable=True),
        sa.Column("priority", sa.String(length=64), nullable=True),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index("ix_email_cases_public_case_key", "email_cases", ["public_case_key"], unique=True)
    op.create_index("ix_email_cases_category_id", "email_cases", ["category_id"])
    op.create_index("ix_email_cases_assigned_user_id", "email_cases", ["assigned_user_id"])

    op.create_table(
        "email_case_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("email_cases.id"), nullable=False),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("mail_items.id"), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index("ix_email_case_events_case_id", "email_case_events", ["case_id"])
    op.create_index("ix_email_case_events_message_id", "email_case_events", ["message_id"])
    op.create_index("ix_email_case_events_event_type", "email_case_events", ["event_type"])

    op.add_column("mail_items", sa.Column("case_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_mail_items_case_id", "mail_items", "email_cases", ["case_id"], ["id"])
    op.create_index("ix_mail_items_case_id", "mail_items", ["case_id"])

    op.add_column("mail_items", sa.Column("in_reply_to_message_id", sa.String(length=500), nullable=True))
    op.add_column("mail_items", sa.Column("references_raw", sa.Text(), nullable=True))
    op.add_column("mail_items", sa.Column("resolution_method", sa.String(length=64), nullable=True))
    op.add_column("mail_items", sa.Column("resolution_confidence", sa.Float(), nullable=True))

    op.add_column("email_messages", sa.Column("case_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_email_messages_case_id", "email_messages", "email_cases", ["case_id"], ["id"])
    op.create_index("ix_email_messages_case_id", "email_messages", ["case_id"])

    op.add_column("email_messages", sa.Column("in_reply_to_message_id", sa.Text(), nullable=True))
    op.add_column("email_messages", sa.Column("references_raw", sa.Text(), nullable=True))
    op.add_column("email_messages", sa.Column("resolution_method", sa.String(length=64), nullable=True))
    op.add_column("email_messages", sa.Column("resolution_confidence", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("email_messages", "resolution_confidence")
    op.drop_column("email_messages", "resolution_method")
    op.drop_column("email_messages", "references_raw")
    op.drop_column("email_messages", "in_reply_to_message_id")
    op.drop_index("ix_email_messages_case_id", table_name="email_messages")
    op.drop_constraint("fk_email_messages_case_id", "email_messages", type_="foreignkey")
    op.drop_column("email_messages", "case_id")

    op.drop_column("mail_items", "resolution_confidence")
    op.drop_column("mail_items", "resolution_method")
    op.drop_column("mail_items", "references_raw")
    op.drop_column("mail_items", "in_reply_to_message_id")
    op.drop_index("ix_mail_items_case_id", table_name="mail_items")
    op.drop_constraint("fk_mail_items_case_id", "mail_items", type_="foreignkey")
    op.drop_column("mail_items", "case_id")

    op.drop_index("ix_email_case_events_event_type", table_name="email_case_events")
    op.drop_index("ix_email_case_events_message_id", table_name="email_case_events")
    op.drop_index("ix_email_case_events_case_id", table_name="email_case_events")
    op.drop_table("email_case_events")

    op.drop_index("ix_email_cases_assigned_user_id", table_name="email_cases")
    op.drop_index("ix_email_cases_category_id", table_name="email_cases")
    op.drop_index("ix_email_cases_public_case_key", table_name="email_cases")
    op.drop_table("email_cases")
