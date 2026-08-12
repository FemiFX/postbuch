# Postbuch

A **correspondence register** — a log of every piece of official mail an
organisation sends or receives, who handled it, what it was about, and how it was
resolved.

German associations, nonprofits and public bodies commonly have to keep one
(*Postbuch*, literally "mail book") for accountability and audit purposes.
Traditionally it's a paper ledger, or a spreadsheet nobody updates. This turns it
into something that fills itself in: mail arrives by IMAP, scanned letters are
OCR'd into searchable text, and every change is audited.

FastAPI · PostgreSQL · Tesseract OCR · S3-compatible storage · OIDC SSO · German UI.

## Try it in about two minutes

```bash
git clone <this-repo> && cd postbuch
cp .env.example .env
docker compose up -d --build
docker compose run --rm web python scripts/seed_demo_data.py
```

Open **http://localhost:8000/auth/login** and use the **developer login** form —
`admin@example.com`, role `super_admin`.

No identity provider, no mail server, no cloud storage account. Postgres, MinIO
and the storage bucket are created for you, and migrations run automatically on
boot.

> The demo data is entirely fictional — invented senders at `.example` domains,
> made-up invoice numbers, placeholder OCR text.

Ports already in use? Every host binding is overridable:

```bash
POSTBUCH_HTTP_PORT=18800 docker compose up -d
```

## What it does

**Incoming paper.** Scan a letter and upload it. Tesseract extracts the text
(`deu+eng`) so the register becomes searchable, and the file goes to
S3-compatible storage rather than a shared drive.

**Incoming email.** A worker polls configured mailboxes over IMAP and turns
messages into register entries. Mailboxes run in one of two modes —
`scan_import` for a dedicated scanner address whose attachments *are* the
correspondence, and `general_triage` for a normal shared inbox where a human
decides what belongs in the register.

**Outgoing mail.** Recorded by hand, with forwarding routes and templates for
mail that gets passed on to someone else.

**Everything else.** Categories with a proposal/approval flow so the taxonomy
doesn't sprawl, duplicate detection, per-item notes and assignment, and an audit
log carrying before/after JSON on every mutating action.

## What's interesting in here

### Two auth paths, one gate

Real deployments use OIDC. Local development uses a form that signs you in
instantly. The switch is `dev_auth_allowed()`, which requires both
`POSTBUCH_DEV_AUTH_ENABLED=true` **and** `POSTBUCH_ENV != "production"` — so the
convenient path can't be switched on by accident in production, even if someone
copies the wrong `.env`.

### An IMAP worker built to survive its own failures

`postbuch/worker/main.py` is a poll loop, not a daemon framework. Each cycle is
wrapped so one unreachable mailbox, one malformed message or one OCR failure logs
and moves on instead of killing the worker. Failed imports are recorded as rows
in `email_messages` with a processing status, so the failure shows up in the UI
rather than only in a log file.

### OCR that knows when not to run

Email arrives with a machine-readable body; a scan doesn't. The pipeline marks
email-sourced items `not_applicable` rather than queueing pointless OCR work, and
`POSTBUCH_OCR_MIN_TEXT_LENGTH` catches PDFs that already carry a text layer.

### An audit log with before/after diffs

`postbuch/services/audit.py` records entity type, action, actor and a JSON diff
for every mutation — which is rather the point of a register that exists for
accountability in the first place.

### A production cutover that prunes as it promotes

[`docs/operations/production_migration.md`](docs/operations/production_migration.md)
is a 15-phase runbook for promoting a development database to production. The
interesting part is `scripts/prune_restored_db_for_production.sql`: rather than
starting empty, it restores the dump and then surgically removes dev users,
non-scan mailboxes, SMTP config and audit history, while **keeping** the
scan-import correspondence history that has genuine archival value.

## Architecture

| Service | Role |
|---|---|
| `db` | PostgreSQL 17, `pg_isready` healthcheck |
| `web` | FastAPI + Jinja; runs `alembic upgrade heads` then uvicorn |
| `worker` | IMAP poll loop; idles harmlessly with no mailboxes configured |
| `minio` | S3-compatible object storage for documents |
| `minio-init` | One-shot bucket bootstrap; `web` and `worker` wait on it completing |
| `caddy` | Reverse proxy on `:8000` |

Roughly 7,100 lines of Python across api / auth / core / db / models / schemas /
services / worker, plus 17 Alembic migrations and 28 Jinja templates.

## Configuration

Everything is `POSTBUCH_`-prefixed and defaults to something that works:

| Variable | Default | Notes |
|---|---|---|
| `POSTBUCH_ENV` | `development` | `production` disables developer login outright |
| `POSTBUCH_DEV_AUTH_ENABLED` | `true` | The zero-config login |
| `POSTBUCH_OIDC_ENABLED` | `false` | Turn on with a real provider |
| `POSTBUCH_S3_*` | bundled MinIO | Any S3-compatible provider works |
| `POSTBUCH_OCR_LANGUAGE` | `deu+eng` | Tesseract language packs in the image |
| `POSTBUCH_IMAP_POLL_SECONDS` | `300` | Applies to all mailboxes |

IMAP credentials are **per mailbox, in the database**, not in the environment —
configured through the admin UI, since an organisation typically has several
addresses with different handling rules.

> ⚠️ Those per-mailbox IMAP passwords are currently stored **unencrypted** in the
> `mailboxes` table. Anyone with database access can read them. Encrypting that
> column is an open item; treat the database as sensitive accordingly.

## Setting up for real

Runbooks live in [`docs/operations/`](docs/operations/):
[local setup](docs/operations/local_setup.md) ·
[OIDC](docs/operations/oidc_setup.md) ·
[IMAP](docs/operations/imap_setup.md) ·
[object storage](docs/operations/hetzner_s3_integration.md) ·
[backup & restore](docs/operations/backup_restore.md) ·
[production migration](docs/operations/production_migration.md)

For OIDC, seed the first administrator explicitly — the gate doesn't
auto-provision:

```bash
docker compose run --rm web python -m postbuch.bootstrap_super_admin \
  --email you@example.org --display-name "Your Name"
```

## Reusable kits

[`kits/`](kits/) contains three self-contained extractions — audit logging,
authentication, and S3 storage — each with its own README and wiring contract,
written to be dropped into a different FastAPI project.

## Known gaps

Stated here rather than discovered later:

- **Per-mailbox IMAP passwords are stored in plaintext** (see above).
- **No test suite.** `pyproject.toml` declares `testpaths = ["tests"]` and pulls
  in pytest, but no `tests/` directory exists.
- **No CI.**
- The worker retries on a fixed interval, with no backoff or dead-letter handling
  beyond the recorded row.

## Licence

MIT — see [LICENSE](LICENSE).
