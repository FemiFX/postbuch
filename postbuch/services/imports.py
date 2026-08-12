from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from imaplib import IMAP4, IMAP4_SSL

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from postbuch.models.correspondence import Correspondence
from postbuch.models.document import Document
from postbuch.models.email_message import EmailMessage
from postbuch.models.enums import (
    CorrespondenceStatus,
    Direction,
    MailboxProcessingMode,
    OCRStatus,
    ProcessingStatus,
    SourceType,
)
from postbuch.models.import_run import ImportRun
from postbuch.models.mail_item import MailItem
from postbuch.models.mailbox import Mailbox
from postbuch.services.audit import create_audit_entry
from postbuch.services.documents import DocumentStoreService
from postbuch.services.ocr import OCRService


DOCUMENT_MIME_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/tiff"}

logger = logging.getLogger(__name__)


@dataclass
class ParsedAttachment:
    filename: str
    mime_type: str
    content: bytes


@dataclass
class ParsedEmail:
    mailbox_name: str
    mailbox_uid: str
    message_id_header: str | None
    in_reply_to_message_id: str | None
    references_raw: str | None
    subject: str
    sender: str | None
    recipient: str | None
    cc: str | None
    received_at: datetime | None
    date_header_at: datetime | None
    raw_headers_json: str
    attachments: list[ParsedAttachment]
    body_text: str
    body_html: str | None
    raw_message: bytes


class EmailParseService:
    def parse(self, mailbox_name: str, mailbox_uid: str, raw_message: bytes) -> ParsedEmail:
        message: Message = message_from_bytes(raw_message)
        attachments: list[ParsedAttachment] = []
        body_text_parts: list[str] = []
        body_html_parts: list[str] = []

        for part in message.walk():
            content_disposition = part.get_content_disposition()
            mime_type = part.get_content_type()

            if content_disposition == "attachment":
                content = part.get_payload(decode=True) or b""
                attachments.append(
                    ParsedAttachment(
                        filename=part.get_filename() or "attachment.bin",
                        mime_type=mime_type,
                        content=content,
                    )
                )
            elif mime_type == "text/plain" and content_disposition != "attachment":
                raw = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                body_text_parts.append(raw.decode(charset, errors="replace"))
            elif mime_type == "text/html" and content_disposition != "attachment":
                raw = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                body_html_parts.append(raw.decode(charset, errors="replace"))

        received_at = self._safe_parse_datetime(message.get("Date"))
        return ParsedEmail(
            mailbox_name=mailbox_name,
            mailbox_uid=mailbox_uid,
            message_id_header=message.get("Message-ID"),
            in_reply_to_message_id=message.get("In-Reply-To"),
            references_raw=message.get("References"),
            subject=self._decode_header(message.get("Subject")) or "(ohne Betreff)",
            sender=self._decode_header(message.get("From")),
            recipient=self._decode_header(message.get("To")),
            cc=self._decode_header(message.get("Cc")),
            received_at=received_at,
            date_header_at=self._safe_parse_datetime(message.get("Date")),
            raw_headers_json=json.dumps(
                {key: str(value) for key, value in message.items()},
                ensure_ascii=False,
            ),
            attachments=attachments,
            body_text="\n".join(body_text_parts),
            body_html="\n".join(body_html_parts) if body_html_parts else None,
            raw_message=raw_message,
        )

    @staticmethod
    def _decode_header(value: str | None) -> str | None:
        if not value:
            return None
        try:
            return str(make_header(decode_header(value)))
        except Exception:
            return value

    @staticmethod
    def _safe_parse_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except (TypeError, ValueError):
            return None


class IMAPPollService:
    def connect(self, mailbox: Mailbox):
        if not mailbox.imap_host or not mailbox.imap_username or not mailbox.imap_password:
            raise ValueError(f"Mailbox '{mailbox.name}' is missing IMAP credentials (imap_host, imap_username, imap_password).")
        if mailbox.imap_use_ssl:
            client = IMAP4_SSL(mailbox.imap_host, mailbox.imap_port)
        else:
            client = IMAP4(mailbox.imap_host, mailbox.imap_port)
        client.login(mailbox.imap_username, mailbox.imap_password)
        return client

    @staticmethod
    def _parse_uidvalidity(status_response: bytes | None) -> str | None:
        if not status_response:
            return None
        m = re.search(r"UIDVALIDITY\s+(\d+)", status_response.decode(errors="replace"))
        return m.group(1) if m else None

    @staticmethod
    def _has_move_capability(client) -> bool:
        try:
            _, caps = client.capability()
            cap_str = caps[0].decode(errors="replace") if caps and caps[0] else ""
            return "MOVE" in cap_str.upper().split()
        except Exception:
            return False

    def fetch_messages(self, mailbox: Mailbox) -> tuple[str | None, list[tuple[str, bytes]]]:
        """Returns (uidvalidity, [(uid, raw_message)])."""
        client = self.connect(mailbox)
        try:
            client.select(mailbox.imap_folder)
            _, status_data = client.status(mailbox.imap_folder, "(UIDVALIDITY)")
            uidvalidity = self._parse_uidvalidity(status_data[0] if status_data else None)
            if mailbox.fetch_since is not None:
                # IMAP SINCE expects DD-Mon-YYYY (e.g. "01-Jan-2024")
                since_str = mailbox.fetch_since.strftime("%d-%b-%Y")
                _, data = client.uid("search", None, f'SINCE "{since_str}"')
            else:
                _, data = client.uid("search", None, "ALL")
            uids = [uid.decode() for uid in data[0].split()] if data and data[0] else []
            messages: list[tuple[str, bytes]] = []
            for uid in uids:
                _, msg_data = client.uid("fetch", uid, "(BODY.PEEK[])")
                raw_message = msg_data[0][1]
                messages.append((uid, raw_message))
            return uidvalidity, messages
        finally:
            client.logout()

    def append_to_sent(
        self,
        host: str,
        username: str,
        password: str,
        msg_bytes: bytes,
        sent_folder: str = "Sent",
        use_ssl: bool = True,
        port: int = 993,
    ) -> None:
        """IMAP-APPEND a sent message into a Sent folder.

        Connects using the supplied credentials (typically the SMTP sender's
        account, not the incoming triage mailbox) so the copy lands in the
        right account's Sent folder.  Appends with \\Seen so it doesn't
        appear as unread.  Callers should catch any exception.
        """
        import imaplib
        import time

        if use_ssl:
            client = IMAP4_SSL(host, port)
        else:
            client = IMAP4(host, port)
        client.login(username, password)
        try:
            date_time = imaplib.Time2Internaldate(time.time())
            client.append(sent_folder, "(\\Seen)", date_time, msg_bytes)
        finally:
            client.logout()

    def move_to_processed(self, mailbox: Mailbox, mailbox_uid: str, source_folder: str | None = None) -> None:
        """Mark message \\Seen and move to processed_folder.

        Uses UID MOVE when the server advertises the MOVE capability (RFC 6851);
        falls back to COPY + STORE \\Deleted + EXPUNGE otherwise.  Tolerates a
        missing UID (message already moved/deleted by another client).

        source_folder overrides mailbox.imap_folder when provided (used so the
        writeback selects the folder that was active at fetch time, not whatever
        the mailbox is currently configured to use).
        """
        folder = source_folder or mailbox.imap_folder
        client = self.connect(mailbox)
        try:
            client.select(folder)
            # Mark seen before moving so the flag is preserved in the destination.
            client.uid("STORE", mailbox_uid, "+FLAGS", "(\\Seen)")
            if self._has_move_capability(client):
                client.uid("MOVE", mailbox_uid, mailbox.processed_folder)
            else:
                client.uid("COPY", mailbox_uid, mailbox.processed_folder)
                client.uid("STORE", mailbox_uid, "+FLAGS", "(\\Deleted)")
                client.expunge()
        finally:
            client.logout()


class CorrespondenceImportService:
    def __init__(self) -> None:
        self.parser = EmailParseService()
        self.store = DocumentStoreService()
        self.ocr = OCRService()

    def process_message(self, db: Session, *, mailbox: Mailbox, mailbox_uid: str, raw_message: bytes) -> ProcessingStatus:
        parsed = self.parser.parse(mailbox.name, mailbox_uid, raw_message)

        # Idempotency: skip if this exact mailbox+UID was already processed (any outcome)
        if db.scalar(select(EmailMessage).where(
            EmailMessage.mailbox_name == parsed.mailbox_name,
            EmailMessage.mailbox_uid == parsed.mailbox_uid,
        )):
            return ProcessingStatus.SKIPPED_DUPLICATE

        # Skip by Message-ID only if a SUCCESSFUL processing already exists
        # (INVALID/FAILED from another mailbox should not block triage processing)
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

        doc_attachments = [a for a in parsed.attachments if a.mime_type in DOCUMENT_MIME_TYPES]
        if len(doc_attachments) != 1:
            email_record.processing_status = ProcessingStatus.INVALID
            email_record.error_message = "Expected exactly one document attachment."
            email_record.processed_at = datetime.now(timezone.utc)
            db.commit()
            return ProcessingStatus.INVALID

        attachment = doc_attachments[0]
        stored = self.store.store_bytes(
            content=attachment.content,
            original_filename=attachment.filename,
            mime_type=attachment.mime_type,
        )

        existing_document = db.scalar(select(Document).where(Document.sha256_hash == stored.sha256_hash))
        if existing_document is not None:
            email_record.processing_status = ProcessingStatus.SKIPPED_DUPLICATE
            email_record.error_message = "Duplicate by document hash"
            email_record.processed_at = datetime.now(timezone.utc)
            db.commit()
            return ProcessingStatus.SKIPPED_DUPLICATE

        ocr_result = self.ocr.extract(attachment.content, attachment.mime_type)
        correspondence = Correspondence(
            direction=mailbox.direction,
            title=parsed.subject or "(ohne Betreff)",
            entry_date=(parsed.received_at or parsed.date_header_at or datetime.now(timezone.utc)).date(),
            status=CorrespondenceStatus.NEW,
            source_type=SourceType.EMAIL_IMPORT,
            source_email_message_id=parsed.message_id_header,
            source_mailbox=parsed.mailbox_name,
            source_email_from=parsed.sender,
            source_email_to=parsed.recipient,
            source_email_subject=parsed.subject,
            source_email_received_at=parsed.received_at,
            source_email_date_header_at=parsed.date_header_at,
            ocr_text=ocr_result.text,
            ocr_status=OCRStatus(ocr_result.status) if ocr_result.status in OCRStatus._value2member_map_ else OCRStatus.FAILED,
            ocr_method=ocr_result.method,
            ocr_confidence=ocr_result.confidence,
            ocr_page_count=ocr_result.page_count,
        )
        db.add(correspondence)
        db.flush()
        db.add(
            Document(
                correspondence_id=correspondence.id,
                original_filename=stored.original_filename,
                stored_filename=stored.stored_filename,
                storage_bucket=stored.storage_bucket,
                storage_key=stored.storage_key,
                mime_type=stored.mime_type,
                file_size_bytes=stored.file_size_bytes,
                sha256_hash=stored.sha256_hash,
                page_count=ocr_result.page_count,
                text_layer_present=ocr_result.text_layer_present,
            )
        )
        create_audit_entry(
            db,
            entity_type="correspondence",
            entity_id=correspondence.id,
            action="imported",
            actor_user_id=None,
            before_json=None,
            after_json={"mailbox": parsed.mailbox_name, "message_id": parsed.message_id_header},
        )
        email_record.processing_status = ProcessingStatus.PROCESSED
        email_record.processed_at = datetime.now(timezone.utc)
        db.commit()
        return ProcessingStatus.PROCESSED


def _summarize_exception(exc: Exception, *, max_len: int = 200) -> str:
    """Return a short, user-safe summary of an exception for the import log.

    Strips SQLAlchemy verbose `[SQL: ...] [parameters: ...]` payload that
    would otherwise leak schema details and overflow the UI.
    """
    if isinstance(exc, IntegrityError):
        message = "Datenbankfehler: Eintrag steht im Konflikt mit einem bestehenden Datensatz."
    else:
        message = f"{type(exc).__name__}: {exc}"
    # Cut off SQL/parameter blobs that some drivers append.
    for marker in ("\n[SQL:", " [SQL:"):
        idx = message.find(marker)
        if idx >= 0:
            message = message[:idx]
    message = " ".join(message.split())
    if len(message) > max_len:
        message = message[: max_len - 1].rstrip() + "…"
    return message


def run_import_cycle(
    db: Session,
    poller: IMAPPollService | None = None,
    importer: CorrespondenceImportService | None = None,
    mail_item_importer: "MailItemImportService | None" = None,
) -> list[ImportRun]:
    from postbuch.services.mail_items import MailItemImportService

    poller = poller or IMAPPollService()
    importer = importer or CorrespondenceImportService()
    mail_item_importer = mail_item_importer or MailItemImportService()
    mailboxes = list(db.scalars(select(Mailbox).where(Mailbox.is_active.is_(True)).order_by(Mailbox.id)))
    runs: list[ImportRun] = []
    for mailbox in mailboxes:
        started_at = datetime.now(timezone.utc)
        run = ImportRun(mailbox_name=mailbox.name, started_at=started_at, status="running")
        db.add(run)
        db.flush()
        run_id = run.id
        create_audit_entry(
            db,
            entity_type="import_run",
            entity_id=run_id,
            action="cycle_started",
            actor_user_id=None,
            before_json=None,
            after_json={"mailbox": mailbox.name, "mailbox_id": mailbox.id},
        )
        db.commit()
        seen = processed = failed = skipped = 0
        notes: list[str] = []
        cycle_status = "completed"
        try:
            uidvalidity, messages = poller.fetch_messages(mailbox)
            seen = len(messages)
            for uid, raw_message in messages:
                try:
                    if mailbox.processing_mode == MailboxProcessingMode.GENERAL_TRIAGE:
                        status_value = mail_item_importer.process_message(
                            db, mailbox=mailbox, mailbox_uid=uid, raw_message=raw_message, uidvalidity=uidvalidity
                        )
                    else:
                        status_value = importer.process_message(db, mailbox=mailbox, mailbox_uid=uid, raw_message=raw_message)
                except Exception as exc:  # pragma: no cover
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    failed += 1
                    notes.append(f"UID {uid}: {_summarize_exception(exc)}")
                    logger.exception("Import failed for mailbox=%s uid=%s", mailbox.name, uid)
                    continue
                if status_value == ProcessingStatus.PROCESSED:
                    processed += 1
                    if mailbox.processing_mode == MailboxProcessingMode.SCAN_IMPORT:
                        try:
                            poller.move_to_processed(mailbox, uid)
                        except Exception as exc:  # pragma: no cover
                            notes.append(f"Move to processed failed for UID {uid}: {_summarize_exception(exc)}")
                elif status_value == ProcessingStatus.SKIPPED_DUPLICATE:
                    skipped += 1
                else:
                    failed += 1
        except Exception as exc:  # pragma: no cover
            cycle_status = "failed"
            notes.append(_summarize_exception(exc))
            logger.exception("Import cycle failed for mailbox=%s", mailbox.name)
            try:
                db.rollback()
            except Exception:
                pass

        run = db.get(ImportRun, run_id)
        if run is None:
            logger.warning("Import run %s disappeared before completion update", run_id)
            continue
        run.status = cycle_status
        run.finished_at = datetime.now(timezone.utc)
        run.messages_seen = seen
        run.messages_processed = processed
        run.messages_failed = failed
        run.messages_skipped_duplicate = skipped
        run.notes = "\n".join(notes) if notes else None
        create_audit_entry(
            db,
            entity_type="import_run",
            entity_id=run_id,
            action="cycle_completed" if cycle_status == "completed" else "cycle_failed",
            actor_user_id=None,
            before_json=None,
            after_json={
                "mailbox": mailbox.name,
                "status": cycle_status,
                "seen": seen,
                "processed": processed,
                "failed": failed,
                "skipped_duplicate": skipped,
                "notes": run.notes,
            },
        )
        runs.append(run)
        db.commit()
    return runs


def perform_imap_writeback(db: Session, item: MailItem, poller: IMAPPollService | None = None) -> None:
    """Mark the source IMAP message \\Seen and move it to the processed folder.

    Best-effort: silently skips if already done, mailbox not found / not
    configured, or the message is missing (moved/deleted externally).
    The caller is responsible for committing the session afterwards.
    """
    if item.imap_seen:
        return
    mailbox = db.get(Mailbox, item.mailbox_id)
    if not mailbox or not mailbox.imap_host:
        logger.warning(
            "IMAP writeback skipped for mail_item %s: mailbox not found or missing imap_host", item.id
        )
        return
    # Use the folder recorded at fetch time; fall back to the mailbox's current config
    # for rows that pre-date migration 0008 where imap_folder is NULL.
    source_folder = item.imap_folder or mailbox.imap_folder
    try:
        (poller or IMAPPollService()).move_to_processed(mailbox, item.mailbox_uid, source_folder=source_folder)
    except Exception as exc:
        logger.warning(
            "IMAP writeback failed for mail_item %s (uid=%s, folder=%s): %s",
            item.id, item.mailbox_uid, source_folder, exc,
        )
        return  # best-effort — don't fail the workflow transition
    item.imap_seen = True
    item.imap_processed_at = datetime.now(timezone.utc)
