# IMAP Setup

## Mailbox model

The application monitors mailbox entries stored in the `mailboxes` table. On first startup it seeds:

- `posteingang` -> `incoming`
- `postausgang` -> `outgoing`

Both use `POSTBUCH_DEFAULT_PROCESSED_FOLDER` as the post-processing target.

## Required environment variables

- `POSTBUCH_IMAP_HOST`
- `POSTBUCH_IMAP_PORT`
- `POSTBUCH_IMAP_USE_SSL`
- `POSTBUCH_IMAP_USERNAME`
- `POSTBUCH_IMAP_PASSWORD`
- `POSTBUCH_IMAP_POLL_SECONDS`

## Import rules

- Exactly one document-like attachment is required for auto-import.
- Duplicate prevention uses mailbox UID, `Message-ID`, and SHA-256 hash.
- Successfully committed messages are copied to the mailbox `Processed` folder and deleted from the source folder.
- Invalid and duplicate messages remain logged in `email_messages` for admin review.

