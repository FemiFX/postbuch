from datetime import datetime

from postbuch.schemas.common import ORMModel
from postbuch.schemas.mail_items import MailItemRead


class EmailCaseEventRead(ORMModel):
    id: int
    case_id: int
    message_id: int | None
    actor_user_id: int | None
    actor_type: str
    event_type: str
    payload_json: dict | None
    created_at: datetime


class EmailCaseRead(ORMModel):
    id: int
    public_case_key: str | None
    subject_canonical: str | None
    status: str
    category_id: int | None
    assigned_user_id: int | None
    created_from_message_id: int | None
    last_message_at: datetime
    last_incoming_at: datetime | None
    last_outgoing_at: datetime | None
    message_count: int
    waiting_reason: str | None
    priority: str | None
    is_closed: bool
    created_at: datetime
    updated_at: datetime


class EmailCaseDetailRead(ORMModel):
    case: EmailCaseRead
    messages: list[MailItemRead]
    events: list[EmailCaseEventRead]
