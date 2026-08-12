-- Prune a restored development database before production cutover.
--
-- Intended flow:
--   1. Restore the development DB dump on the destination server.
--   2. Run alembic upgrade heads.
--   3. Run this script against the restored DB.
--   4. Seed the production super admin with postbuch.bootstrap_super_admin.
--   5. Configure OIDC env vars and production mailbox credentials/fetch_since.
--
-- What this keeps:
--   - correspondence/documents created from scan_import mailboxes
--   - processed email_messages for those scan_import mailboxes, for import history/idempotency
--   - scan_import mailbox rows, deactivated for safe production configuration
--   - categories referenced by kept correspondence
--
-- What this removes:
--   - general-triage mail_items, attachments, cases, and case events
--   - email_messages not belonging to scan_import mailboxes or not successfully processed
--   - manual/development correspondence records
--   - all category proposals, audit log entries, SMTP config, and users
--   - non-scan-import mailbox rows

BEGIN;

CREATE TEMP TABLE kept_scan_mailboxes ON COMMIT DROP AS
SELECT name
FROM mailboxes
WHERE processing_mode = 'scan_import';

CREATE TEMP TABLE kept_correspondence ON COMMIT DROP AS
SELECT id
FROM correspondence
WHERE source_type = 'email_import'
  AND source_mailbox IN (SELECT name FROM kept_scan_mailboxes);

-- General email triage data is not part of scan-import history.
UPDATE email_messages SET case_id = NULL WHERE case_id IS NOT NULL;
DELETE FROM email_case_events;
UPDATE mail_items SET case_id = NULL WHERE case_id IS NOT NULL;
UPDATE email_cases SET created_from_message_id = NULL WHERE created_from_message_id IS NOT NULL;
DELETE FROM mail_item_attachments;
DELETE FROM mail_items;
DELETE FROM email_cases;

-- Keep only successful scan-import email logs. Failed/invalid rows can block
-- future retries by mailbox UID, and are not part of the preserved history.
DELETE FROM email_messages
WHERE mailbox_name NOT IN (SELECT name FROM kept_scan_mailboxes)
   OR processing_status <> 'processed';

-- Keep only scan-import correspondence and their files.
UPDATE correspondence
SET duplicate_of_correspondence_id = NULL,
    is_duplicate_flag = false
WHERE duplicate_of_correspondence_id IS NOT NULL
  AND duplicate_of_correspondence_id NOT IN (SELECT id FROM kept_correspondence);

DELETE FROM documents
WHERE correspondence_id NOT IN (SELECT id FROM kept_correspondence);

DELETE FROM correspondence
WHERE id NOT IN (SELECT id FROM kept_correspondence);

-- Remove user-governed development metadata.
DELETE FROM category_proposal;
DELETE FROM audit_log;

-- Keep only categories that are still referenced by preserved correspondence.
UPDATE category
SET created_by_user_id = NULL,
    approved_by_user_id = NULL;

DELETE FROM category
WHERE id NOT IN (
    SELECT DISTINCT category_id
    FROM correspondence
    WHERE category_id IS NOT NULL
);

-- Keep scan mailboxes, but deactivate them until production credentials and
-- fetch_since are reviewed. Remove other mailbox rows such as dev triage.
DELETE FROM mailboxes
WHERE name NOT IN (SELECT name FROM kept_scan_mailboxes);

UPDATE mailboxes
SET is_active = false
WHERE name IN (SELECT name FROM kept_scan_mailboxes);

-- SMTP config commonly contains environment-specific credentials.
DELETE FROM smtp_config;

-- Remove all development users. Seed the production admin after this script.
UPDATE correspondence
SET created_by_user_id = NULL,
    updated_by_user_id = NULL;

DELETE FROM users;

COMMIT;
