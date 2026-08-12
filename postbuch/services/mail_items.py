from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from postbuch.models.email_message import EmailMessage
from postbuch.models.enums import MailItemStatus, ProcessingStatus
from postbuch.models.mail_item import MailItem
from postbuch.models.mail_item_attachment import MailItemAttachment
from postbuch.models.mailbox import Mailbox
from postbuch.services.mail_case_resolution import attach_mail_item_to_case, resolve_case_for_mail_item
from postbuch.services.documents import DocumentStoreService
from postbuch.services.imports import EmailParseService


class MailItemImportService:
    def __init__(self) -> None:
        self.parser = EmailParseService()
        self.store = DocumentStoreService()

    def process_message(self, db: Session, *, mailbox: Mailbox, mailbox_uid: str, raw_message: bytes, uidvalidity: str | None = None) -> ProcessingStatus:
        parsed = self.parser.parse(mailbox.name, mailbox_uid, raw_message)

        # Idempotency: skip if this exact mailbox+UID was already processed (any outcome)
        if db.scalar(select(EmailMessage).where(
            EmailMessage.mailbox_name == parsed.mailbox_name,
            EmailMessage.mailbox_uid == parsed.mailbox_uid,
        )):
            return ProcessingStatus.SKIPPED_DUPLICATE

        # Skip by Message-ID only if a SUCCESSFUL processing already exists
        if parsed.message_id_header and db.scalar(
            select(EmailMessage).where(
                EmailMessage.message_id_header == parsed.message_id_header,
                EmailMessage.processing_status == ProcessingStatus.PROCESSED,
            )
        ):
            return ProcessingStatus.SKIPPED_DUPLICATE

        email_record = EmailMessage(
            mailbox_name=parsed.mailbox_name,
            mailbox_uid=parsed.mailbox_uid,
            message_id_header=parsed.message_id_header,
            in_reply_to_message_id=parsed.in_reply_to_message_id,
            references_raw=parsed.references_raw,
            subject=parsed.subject,
            sender=parsed.sender,
            recipient=parsed.recipient,
            received_at=parsed.received_at,
            raw_headers_json=parsed.raw_headers_json,
            processing_status=ProcessingStatus.FAILED,
        )
        db.add(email_record)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return ProcessingStatus.SKIPPED_DUPLICATE

        mail_item = MailItem(
            mailbox_id=mailbox.id,
            message_id_header=parsed.message_id_header,
            in_reply_to_message_id=parsed.in_reply_to_message_id,
            references_raw=parsed.references_raw,
            mailbox_uid=parsed.mailbox_uid,
            subject=parsed.subject,
            sender=parsed.sender,
            recipient=parsed.recipient,
            cc=parsed.cc,
            received_at=parsed.received_at,
            body_text=parsed.body_text,
            body_html=parsed.body_html,
            has_attachments=len(parsed.attachments) > 0,
            raw_headers_json=parsed.raw_headers_json,
            status=MailItemStatus.NEW,
            imap_folder=mailbox.imap_folder,
            imap_uidvalidity=uidvalidity,
        )
        db.add(mail_item)
        db.flush()

        case, method, confidence, _ = resolve_case_for_mail_item(
            db,
            subject=parsed.subject,
            message_id_header=parsed.message_id_header,
            in_reply_to_message_id=parsed.in_reply_to_message_id,
            references_raw=parsed.references_raw,
            received_at=parsed.received_at,
        )
        attach_mail_item_to_case(
            db,
            case=case,
            mail_item=mail_item,
            resolution_method=method,
            resolution_confidence=confidence,
        )
        email_record.case_id = case.id
        email_record.resolution_method = method
        email_record.resolution_confidence = confidence

        for attachment in parsed.attachments:
            stored = self.store.store_bytes(
                content=attachment.content,
                original_filename=attachment.filename,
                mime_type=attachment.mime_type,
            )
            db.add(
                MailItemAttachment(
                    mail_item_id=mail_item.id,
                    original_filename=stored.original_filename,
                    stored_filename=stored.stored_filename,
                    storage_bucket=stored.storage_bucket,
                    storage_key=stored.storage_key,
                    mime_type=stored.mime_type,
                    file_size_bytes=stored.file_size_bytes,
                    sha256_hash=stored.sha256_hash,
                )
            )

        email_record.processing_status = ProcessingStatus.PROCESSED
        email_record.processed_at = datetime.now(timezone.utc)
        db.commit()
        return ProcessingStatus.PROCESSED
