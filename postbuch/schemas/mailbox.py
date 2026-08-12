from pydantic import BaseModel, Field

from postbuch.models.enums import Direction, MailboxProcessingMode
from postbuch.schemas.common import ORMModel


class MailboxRead(ORMModel):
    id: int
    name: str
    direction: Direction
    processing_mode: MailboxProcessingMode
    imap_folder: str
    processed_folder: str
    is_active: bool
    imap_host: str | None
    imap_port: int
    imap_use_ssl: bool
    imap_username: str | None


class MailboxCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    direction: Direction
    processing_mode: MailboxProcessingMode = MailboxProcessingMode.SCAN_IMPORT
    imap_folder: str = "INBOX"
    processed_folder: str = "Processed"
    is_active: bool = True
    imap_host: str = Field(min_length=1, max_length=255)
    imap_port: int = 993
    imap_use_ssl: bool = True
    imap_username: str = Field(min_length=1, max_length=255)
    imap_password: str = Field(min_length=1, max_length=500)


class MailboxUpdate(BaseModel):
    direction: Direction
    processing_mode: MailboxProcessingMode
    imap_folder: str
    processed_folder: str
    is_active: bool
    imap_host: str
    imap_port: int
    imap_use_ssl: bool
    imap_username: str
    imap_password: str | None = None  # None = keep existing
