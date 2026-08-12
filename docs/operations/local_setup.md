# Local Setup

## Requirements

- Docker and Docker Compose
- Nextcloud OIDC client credentials
- IMAP credentials for the monitored mailbox account

## Start the stack

1. Copy `.env.example` to `.env`.
2. Set `POSTBUCH_SECRET_KEY`, database URL, OIDC values, and IMAP values.
3. Build and start:

```bash
docker compose up --build
```

4. Run migrations:

```bash
docker compose exec web alembic upgrade head
```

5. Open `http://localhost:8000`.

## Development notes

- Default seeded mailboxes:
  - `posteingang`
  - `postausgang`
- Files are stored in S3-compatible object storage using the `POSTBUCH_S3_*` settings.
- `POSTBUCH_STORAGE_ROOT` is only used as a local source path when running one-time migration scripts for legacy files.
- The worker runs continuously and polls IMAP every `POSTBUCH_IMAP_POLL_SECONDS`.
- For local UI testing without OIDC, set `POSTBUCH_DEV_AUTH_ENABLED=true` and sign in via `/auth/login`.
