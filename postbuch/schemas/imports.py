from datetime import datetime

from postbuch.schemas.common import ORMModel


class ImportRunRead(ORMModel):
    id: int
    mailbox_name: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    messages_seen: int
    messages_processed: int
    messages_failed: int
    messages_skipped_duplicate: int
    notes: str | None


class EmailMessageRead(ORMModel):
    id: int
    mailbox_name: str
    mailbox_uid: str
    message_id_header: str | None
    subject: str | None
    sender: str | None
    recipient: str | None
    processing_status: str
    error_message: str | None

