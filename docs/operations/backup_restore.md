# Backup and Restore

## What to back up

- PostgreSQL database
- S3 bucket contents used for documents and attachments
- `.env` or secret-management source for OIDC/IMAP settings

## Suggested backup commands

```bash
docker compose exec db pg_dump -U postbuch -d postbuch > postbuch.sql
```

## Restore outline

1. Stop the application.
2. Restore PostgreSQL from `postbuch.sql`.
3. Restore object storage bucket contents from your S3 backup.
4. Ensure `.env` contains the original S3/OIDC/IMAP configuration.
5. Start services and verify downloads and correspondence detail views.
