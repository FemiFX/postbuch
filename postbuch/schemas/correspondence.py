from datetime import date, datetime

from pydantic import BaseModel, Field

from postbuch.models.enums import CorrespondenceStatus, Direction, OCRStatus, SourceType
from postbuch.schemas.category import CategoryRead
from postbuch.schemas.common import ORMModel


class CorrespondenceRead(ORMModel):
    id: int
    direction: Direction
    title: str
    entry_date: date
    status: CorrespondenceStatus
    category_id: int | None
    completion_note: str | None
    notes: str | None
    placement_location: str | None
    handoff_target: str | None
    notification_done: bool
    notification_channel: str | None
    notified_party: str | None
    processing_note: str | None
    ocr_text: str | None
    ocr_status: OCRStatus
    ocr_method: str | None
    source_type: SourceType
    source_email_message_id: str | None
    source_mailbox: str | None
    source_email_from: str | None
    source_email_to: str | None
    source_email_subject: str | None
    source_email_received_at: datetime | None
    source_email_date_header_at: datetime | None
    duplicate_of_correspondence_id: int | None
    is_duplicate_flag: bool
    category: CategoryRead | None = None


class CorrespondenceCreate(BaseModel):
    direction: Direction = Direction.OUTGOING
    title: str = Field(min_length=1, max_length=500)
    entry_date: date
    category_id: int | None = None
    completion_note: str | None = None
    notes: str | None = None
    source_type: SourceType = SourceType.MANUAL_ENTRY


class CorrespondenceUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    entry_date: date
    status: CorrespondenceStatus
    category_id: int | None = None
    completion_note: str | None = None
    notes: str | None = None
    placement_location: str | None = None
    handoff_target: str | None = None
    notification_done: bool = False
    notification_channel: str | None = None
    notified_party: str | None = None
    processing_note: str | None = None


class CorrespondenceStatusUpdate(BaseModel):
    status: CorrespondenceStatus
    completion_note: str | None = None


class CorrespondenceDirectionUpdate(BaseModel):
    direction: Direction


class CorrespondenceFilter(BaseModel):
    query: str | None = None
    direction: Direction | None = None
    status: CorrespondenceStatus | None = None
    category_id: int | None = None
    source_mailbox: str | None = None
    date_from: date | None = None
    date_to: date | None = None
