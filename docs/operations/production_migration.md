# Production Migration Runbook

This runbook describes how to move Postbuch to a production server while preserving
only the useful scan-import history from development.

The intended outcome is:

- Keep correspondence records created from scan-import mailboxes such as
  `posteingang` and `postausgang`.
- Keep the document metadata that points to the existing S3 bucket objects.
- Keep successful scan-import `email_messages` so already imported scanner emails
  remain known to the application.
- Remove development users, local/dev login identities, general triage emails,
  email cases, audit entries, proposals, SMTP settings, and non-scan mailboxes.
- Seed a fresh production super admin for OIDC login.
- Configure production database credentials and clean Nextcloud OIDC credentials.
- Re-enable the scan mailboxes only after reviewing production IMAP credentials
  and the go-live `fetch_since` date.

## Important Behavior

Scan-import mailboxes and general triage mailboxes are handled differently.

- `scan_import` mailboxes: after a message is successfully imported into a
  correspondence record, the worker immediately marks the source IMAP message
  seen and moves it to the configured `processed_folder`. It does not wait for
  the correspondence to be marked `erledigt`.
- `general_triage` mailboxes: messages are imported as `mail_items` and remain
  in the source folder until the mail item is marked `geschlossen` or `spam`.

Because the existing `posteingang` / `postausgang` scan emails have already been
moved to the processed folder, preserving their database records is the right
approach. Otherwise the application would lose the correspondence/document
history while the source messages are no longer available in the inbox.

## Assumptions

- The S3 bucket stays the same.
- The existing S3 objects are kept.
- Production may use a new S3 key prefix for future files, but this is optional.
- The production server starts with a fresh Docker/Postgres volume.
- Production uses `POSTBUCH_ENV=production`.
- Production uses OIDC via Nextcloud, not the development login form.
- You have shell access to both the old/development server and the new production
  server.

## Files Involved

- Cleanup script:
  `scripts/prune_restored_db_for_production.sql`
- Environment template:
  `.env.example`
- Compose stack:
  `docker-compose.yml`
- OIDC setup notes:
  `docs/operations/oidc_setup.md`

## Phase 1: Prepare the Source Database

Pick a maintenance window. The safest cutover is to stop the app worker before
taking the dump so no import run is writing while the backup is created.

On the source server:

```bash
docker compose ps
```

Stop the worker and web process if you want a fully quiet database:

```bash
docker compose stop worker web
```

Create a custom-format Postgres dump:

```bash
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > postbuch-dev-source.dump
```

Optional verification:

```bash
ls -lh postbuch-dev-source.dump
```

If you stopped the source app only for the dump and still need it locally, start
it again:

```bash
docker compose up -d web worker
```

## Phase 2: Transfer Deployment Inputs

Transfer these items to the production server:

- `postbuch-dev-source.dump`
- The application source tree or built image
- `docker-compose.yml`
- `Caddyfile` or your production reverse-proxy configuration
- `.env` created from `.env.example`, with production values

Example using `scp`:

```bash
scp postbuch-dev-source.dump deploy@example.com:/srv/postbuch/
```

If you deploy from Git instead, clone or pull the target revision on the
production server:

```bash
git clone <repo-url> /srv/postbuch
cd /srv/postbuch
```

## Phase 3: Create the Production Environment File

On the production server, create `.env` from `.env.example`:

```bash
cp .env.example .env
```

Set production values:

```env
POSTBUCH_ENV=production
POSTBUCH_APP_NAME=Postbuch
POSTBUCH_SECRET_KEY=<long-random-production-secret>
POSTBUCH_DATABASE_URL=postgresql+psycopg://<prod_db_user>:<prod_db_password>@db:5432/<prod_db_name>
POSTBUCH_SESSION_COOKIE_NAME=postbuch_session

POSTBUCH_S3_ENDPOINT=<existing-s3-endpoint>
POSTBUCH_S3_REGION=<existing-s3-region>
POSTBUCH_S3_ACCESS_KEY_ID=<production-s3-access-key>
POSTBUCH_S3_SECRET_ACCESS_KEY=<production-s3-secret-key>
POSTBUCH_S3_BUCKET=<existing-bucket>
POSTBUCH_S3_KEY_PREFIX=uploads
POSTBUCH_S3_PRESIGNED_URL_TTL_SECONDS=3600

POSTBUCH_OIDC_ENABLED=true
POSTBUCH_OIDC_SERVER_METADATA_URL=<nextcloud-openid-configuration-url>
POSTBUCH_OIDC_CLIENT_ID=<production-client-id>
POSTBUCH_OIDC_CLIENT_SECRET=<production-client-secret>
POSTBUCH_OIDC_SCOPES=openid profile email
POSTBUCH_DEV_AUTH_ENABLED=false

POSTBUCH_IMAP_POLL_SECONDS=300
POSTBUCH_OCR_LANGUAGE=deu+eng
POSTBUCH_OCR_MIN_TEXT_LENGTH=80
```

The database credentials must also match the `db` service environment in
`docker-compose.yml`:

```yaml
POSTGRES_DB: <prod_db_name>
POSTGRES_USER: <prod_db_user>
POSTGRES_PASSWORD: <prod_db_password>
```

Do not use the development database password in production.

## Phase 4: Configure Nextcloud OIDC

In Nextcloud, create or update the OIDC client for the production URL.

Use this redirect URI:

```text
https://<production-hostname>/auth/callback
```

Record these values in `.env`:

- `POSTBUCH_OIDC_SERVER_METADATA_URL`
- `POSTBUCH_OIDC_CLIENT_ID`
- `POSTBUCH_OIDC_CLIENT_SECRET`
- `POSTBUCH_OIDC_SCOPES`

Production should use:

```env
POSTBUCH_OIDC_ENABLED=true
POSTBUCH_DEV_AUTH_ENABLED=false
POSTBUCH_ENV=production
```

The code blocks development login automatically when `POSTBUCH_ENV=production`.

## Phase 5: Start the Production Database

Start only the database first:

```bash
docker compose up -d db
```

Wait until it is healthy:

```bash
docker compose ps db
```

If the database volume already contains test data, stop here and decide whether
to remove/recreate the volume. Do not restore into an unknown database unless you
intend to replace it.

## Phase 6: Restore the Source Dump

Copy `postbuch-dev-source.dump` into the production project directory if it is
not already there.

Restore into the production database:

```bash
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < postbuch-dev-source.dump
```

If the database was empty, `--clean --if-exists` may print notices about missing
objects. Those notices are expected.

## Phase 7: Build and Run Migrations

Build the application image:

```bash
docker compose build
```

Run migrations to ensure the restored schema matches the current code:

```bash
docker compose run --rm web alembic upgrade heads
```

This step should be run before pruning, so the cleanup script can rely on the
current tables and columns.

## Phase 8: Prune Development Data

Run the cleanup script:

```bash
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < scripts/prune_restored_db_for_production.sql
```

The script is destructive by design. It deletes development-only data and all
existing users from the restored database.

It keeps:

- `correspondence` rows where `source_type = 'email_import'` and the
  `source_mailbox` belongs to a `scan_import` mailbox.
- `documents` linked to those kept correspondence rows.
- successful `email_messages` for scan-import mailboxes.
- scan-import mailbox rows, but deactivated.
- categories still referenced by kept correspondence.

It removes:

- all users
- all audit log rows
- all category proposals
- all general triage mail items
- all mail item attachments
- all email cases and case events
- all non-scan-import mailboxes
- all SMTP config rows
- invalid, failed, skipped, or non-scan `email_messages`
- non-scan or manual/development correspondence rows

## Phase 9: Verify the Pruned Database

Open a database shell:

```bash
docker compose exec db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

Run these checks:

```sql
SELECT count(*) AS users FROM users;

SELECT name, processing_mode, is_active, imap_folder, processed_folder, fetch_since
FROM mailboxes
ORDER BY id;

SELECT source_mailbox, count(*) AS correspondence_count
FROM correspondence
GROUP BY source_mailbox
ORDER BY source_mailbox;

SELECT mailbox_name, processing_status, count(*) AS email_message_count
FROM email_messages
GROUP BY mailbox_name, processing_status
ORDER BY mailbox_name, processing_status;

SELECT count(*) AS mail_items FROM mail_items;
SELECT count(*) AS email_cases FROM email_cases;
SELECT count(*) AS documents FROM documents;
```

Expected results:

- `users` is `0` before seeding the production admin.
- `mail_items` is `0`.
- `email_cases` is `0`.
- scan-import mailboxes exist but `is_active = false`.
- correspondence and document counts match the scan-import history you intend to
  keep.

Exit `psql`:

```sql
\q
```

## Phase 10: Seed the Production Super Admin

Seed the first OIDC-approved production administrator:

```bash
docker compose run --rm web python -m postbuch.bootstrap_super_admin \
  --email admin@example.com \
  --display-name "Initial Admin"
```

Use the exact email address that Nextcloud will return in the OIDC `email`
claim. The first successful login will bind that user row to the OIDC subject.

If the email address does not match the OIDC email claim, login will be denied
because Postbuch requires preapproved active users.

## Phase 11: Start the Full Stack

Start the application:

```bash
docker compose up -d
```

Check service status:

```bash
docker compose ps
```

Check logs:

```bash
docker compose logs --tail=100 web
docker compose logs --tail=100 worker
```

The worker may run, but the scan-import mailboxes should still be inactive after
the prune script. This is intentional.

## Phase 12: First OIDC Login

Open the production URL:

```text
https://<production-hostname>/
```

Expected behavior:

1. The app redirects to Nextcloud OIDC.
2. Nextcloud authenticates the admin.
3. Postbuch finds the pre-seeded user by email.
4. Postbuch binds `oidc_subject` and `oidc_issuer`.
5. The admin lands on the dashboard.

If login fails with "not pre-approved", check that the seeded email exactly
matches the email claim returned by Nextcloud.

## Phase 13: Configure Production Mailboxes

Go to:

```text
/admin/mailboxes
```

For `posteingang` and `postausgang`:

1. Confirm `processing_mode = scan_import`.
2. Confirm `imap_folder` points to the source folder to poll.
3. Confirm `processed_folder` points to the folder where imported messages
   should be moved.
4. Set the production IMAP host, port, SSL setting, username, and password.
5. Set `fetch_since` to the go-live date.
6. Activate the mailbox only when ready.

Important: IMAP `SINCE` is date-based, not exact-time-based. If you set
`fetch_since` to `2026-05-01`, the search includes messages from all of
May 1, 2026 according to the IMAP server's date handling.

Because earlier scan messages were already moved to the processed folder, keeping
their DB records preserves history. The go-live `fetch_since` controls what the
worker should begin importing from the active source folders after production
starts.

## Phase 14: Configure SMTP If Needed

The prune script deletes `smtp_config` because it can contain development
credentials.

If outbound forwarding/replies are used, configure SMTP again through:

```text
/admin/mailboxes
```

Save the production SMTP host, port, username, password, from address, and TLS
setting.

## Phase 15: Final Verification

Verify preserved correspondence:

- Open the correspondence register.
- Open several imported scan records from `posteingang` and `postausgang`.
- Confirm document download/preview works.
- Confirm S3 links resolve correctly.

Verify users:

- Open `/admin/users`.
- Confirm only production-seeded users exist.
- Add any additional production users through the admin UI.

Verify mailbox safety:

- Confirm only intended scan-import mailboxes are active.
- Confirm any production general-triage mailbox is newly created and points to
  the production mailbox, not a development mailbox.

Verify import behavior:

```bash
docker compose logs --tail=200 worker
```

Optionally trigger an import cycle from the admin import monitor after activating
mailboxes.

## Rollback Notes

Before the cutover, keep:

- the original `postbuch-dev-source.dump`
- the old server untouched until production has been verified
- a copy of the production `.env`

If pruning was run incorrectly on the production database, the practical rollback
is to recreate the production database volume, restore `postbuch-dev-source.dump`
again, rerun migrations, adjust the cleanup script if necessary, and rerun the
prune step.

Do not rerun the prune script on a production database after real production
users or mailboxes have been added unless you intentionally want to remove them.

