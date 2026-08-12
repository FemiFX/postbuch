from datetime import datetime

from pydantic import BaseModel

from postbuch.models.enums import MailItemActionType, MailItemStatus
from postbuch.schemas.common import ORMModel


class MailItemAttachmentRead(ORMModel):
    id: int
    mail_item_id: int
    original_filename: str
    stored_filename: str
    storage_bucket: str
    storage_key: str
    mime_type: str
    file_size_bytes: int
    sha256_hash: str
    created_at: datetime


class MailItemRead(ORMModel):
    id: int
    case_id: int | None
    mailbox_id: int
    message_id_header: str | None
    in_reply_to_message_id: str | None
    references_raw: str | None
    mailbox_uid: str
    subject: str
    sender: str | None
    recipient: str | None
    cc: str | None
    received_at: datetime | None
    body_text: str
    body_html: str | None
    has_attachments: bool
    status: MailItemStatus
    category_id: int | None
    assigned_to_user_id: int | None
    action_type: MailItemActionType | None
    action_status: str | None
    resolution_note: str | None
    forward_targets_json: str | None
    reply_subject: str | None
    reply_body: str | None
    resolution_method: str | None
    resolution_confidence: float | None
    processed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    attachments: list[MailItemAttachmentRead] = []


class MailItemTimelineEventRead(BaseModel):
    id: int
    action: str
    actor_user_id: int | None = None
    actor_display_name: str | None = None
    before_json: dict | None = None
    after_json: dict | None = None
    created_at: datetime


class MailItemNoteRead(BaseModel):
    id: int
    mail_item_id: int
    author_user_id: int | None = None
    author_display_name: str | None = None
    author_initials: str | None = None
    body: str
    created_at: datetime


class MailItemNoteCreate(BaseModel):
    body: str


class MailItemUpdate(BaseModel):
    status: MailItemStatus | None = None
    category_id: int | None = None
    assigned_to_user_id: int | None = None
    action_type: MailItemActionType | None = None
    resolution_note: str | None = None
    reply_subject: str | None = None
    reply_body: str | None = None
    forward_targets_json: str | None = None


class MailItemAssignCategory(BaseModel):
    category_id: int


class MailItemFilter(BaseModel):
    status: MailItemStatus | None = None
    category_id: int | None = None
    assigned_to_user_id: int | None = None
    mailbox_id: int | None = None
    query: str | None = None
