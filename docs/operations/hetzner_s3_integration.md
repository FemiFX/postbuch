# Hetzner S3 Object Storage Integration

This document explains how Postbuch stores document binaries and email
attachments in Hetzner Object Storage using the S3-compatible API.

It is written as both project documentation and an implementation guide for
reusing the same pattern in another FastAPI/SQLAlchemy application.

## Summary

Postbuch does not store uploaded files or imported email attachments in
PostgreSQL. PostgreSQL stores the metadata needed to find and validate each
object, while Hetzner Object Storage stores the binary payload.

The core model is:

- The app uploads bytes to a private S3-compatible bucket.
- Each object receives a generated key such as
  `uploads/2026/04/<uuid>.pdf`.
- The database stores `storage_bucket`, `storage_key`, original filename, MIME
  type, file size, and SHA-256 hash.
- Downloads are served through short-lived presigned URLs.
- The bucket can stay private; users never need public bucket permissions.

The implementation lives mainly in:

- `postbuch/services/documents.py`
- `postbuch/models/document.py`
- `postbuch/models/mail_item_attachment.py`
- `postbuch/services/imports.py`
- `postbuch/services/mail_items.py`
- `scripts/migrate_local_files_to_s3.py`

## Hetzner Object Storage Basics

Hetzner Object Storage is S3-compatible and uses location-bound endpoints such
as:

```text
https://fsn1.your-objectstorage.com
https://nbg1.your-objectstorage.com
https://hel1.your-objectstorage.com
```

The location is also used as the S3 region:

```text
fsn1
nbg1
hel1
```

Postbuch currently uses the standard boto3 S3 client with:

- a custom `endpoint_url`
- `region_name`
- project access key
- project secret key
- S3 signature version 4

Official Hetzner references:

- Object Storage overview:
  https://www.hetzner.com/storage/object-storage/overview/
- S3-compatible tools:
  https://docs.hetzner.com/storage/object-storage/getting-started/using-s3-api-tools/
- S3-compatible libraries:
  https://docs.hetzner.com/storage/object-storage/getting-started/using-libraries/
- Buckets and objects:
  https://docs.hetzner.com/storage/object-storage/faq/buckets-objects/

## Environment Variables

Postbuch reads S3 settings through `postbuch/core/config.py`.

Required:

```env
POSTBUCH_S3_ENDPOINT=https://fsn1.your-objectstorage.com
POSTBUCH_S3_REGION=fsn1
POSTBUCH_S3_ACCESS_KEY_ID=<hetzner-access-key>
POSTBUCH_S3_SECRET_ACCESS_KEY=<hetzner-secret-key>
POSTBUCH_S3_BUCKET=<bucket-name>
```

Optional:

```env
POSTBUCH_S3_KEY_PREFIX=uploads
POSTBUCH_S3_PRESIGNED_URL_TTL_SECONDS=3600
```

Legacy migration only:

```env
POSTBUCH_STORAGE_ROOT=/data/storage
```

The app also accepts the shorter aliases `S3_ENDPOINT`, `S3_REGION`,
`S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, and `S3_BUCKET`, but the
`POSTBUCH_` names are preferred.

## Bucket Setup

Create the bucket in the Hetzner Console or with an S3-compatible tool. Keep the
bucket private.

Recommended production properties:

- Private visibility.
- A dedicated bucket for Postbuch or a dedicated prefix inside a shared bucket.
- One access key scoped to the Hetzner project that owns the bucket.
- Separate credentials for development and production where possible.
- A stable `POSTBUCH_S3_KEY_PREFIX`; changing it only affects future uploads.

Example production prefix:

```env
POSTBUCH_S3_KEY_PREFIX=production/uploads
```

Example development prefix:

```env
POSTBUCH_S3_KEY_PREFIX=development/uploads
```

The bucket itself can stay the same if prefixes clearly separate environments.

## Data Model

Postbuch stores object references in two tables.

### Documents

`documents` stores files attached to correspondence records:

```text
storage_bucket
storage_key
original_filename
stored_filename
mime_type
file_size_bytes
sha256_hash
```

`storage_key` is unique. `sha256_hash` is indexed and used for duplicate
detection.

### Mail Item Attachments

`mail_item_attachments` stores attachments imported from general triage mail:

```text
storage_bucket
storage_key
original_filename
stored_filename
mime_type
file_size_bytes
sha256_hash
```

The shape intentionally mirrors `documents`, so downloads and future migration
logic can treat both object types consistently.

## Upload Flow

All upload paths use `DocumentStoreService`.

The service:

1. Validates the S3 configuration.
2. Builds a boto3 S3 client for the Hetzner endpoint.
3. Generates a stable object key using prefix, year/month, UUID, and extension.
4. Uploads the object using `upload_fileobj`.
5. Stores the MIME type as object metadata via `ContentType`.
6. Computes SHA-256 from the uploaded bytes.
7. Returns a `StoredDocument` value object for database persistence.

Current key pattern:

```text
<POSTBUCH_S3_KEY_PREFIX>/<YYYY>/<MM>/<uuid><extension>
```

Example:

```text
uploads/2026/04/c7d7da036a5045bc8ee6c4d1f3193c2a.pdf
```

The object key is intentionally not derived from the original filename. That
avoids collisions, leaking user-provided names into storage paths, and problems
with special characters.

## Download Flow

Postbuch does not stream private S3 objects through the web container. Instead,
the app generates a presigned GET URL and redirects the browser to it.

The app includes response overrides:

- `ResponseContentDisposition`
- `ResponseContentType`

This lets the app control whether the browser downloads the file or opens it
inline, without changing bucket visibility.

The default expiry is:

```env
POSTBUCH_S3_PRESIGNED_URL_TTL_SECONDS=3600
```

Use a shorter TTL if links are commonly exposed outside trusted sessions.

## Core Python Pattern

This is the essential boto3 pattern used in Postbuch:

```python
import boto3
from botocore.client import Config

client = boto3.client(
    "s3",
    endpoint_url="https://fsn1.your-objectstorage.com",
    aws_access_key_id="<access-key>",
    aws_secret_access_key="<secret-key>",
    region_name="fsn1",
    config=Config(signature_version="s3v4"),
)

client.upload_fileobj(
    Fileobj=file_obj,
    Bucket="postbuch",
    Key="uploads/2026/04/example.pdf",
    ExtraArgs={"ContentType": "application/pdf"},
)

url = client.generate_presigned_url(
    "get_object",
    Params={
        "Bucket": "postbuch",
        "Key": "uploads/2026/04/example.pdf",
        "ResponseContentDisposition": 'attachment; filename="example.pdf"',
        "ResponseContentType": "application/pdf",
    },
    ExpiresIn=3600,
)
```

## Where Postbuch Calls Storage

### Manual Correspondence Uploads

Manual uploads call:

```python
stored = await DocumentStoreService().store_upload(upload)
```

The returned metadata is passed into correspondence creation and persisted as a
`Document` row.

### Scan Import Mailboxes

Scan-import mailboxes expect exactly one document-like attachment. During import:

1. The email attachment is parsed.
2. The attachment bytes are uploaded to S3.
3. The SHA-256 hash is checked against existing documents.
4. A `correspondence` row is created.
5. A `documents` row is created with the S3 metadata.
6. The source IMAP message is moved to the processed folder after successful
   import.

### General Triage Mailboxes

General triage imports can store multiple attachments. During import:

1. A `mail_items` row is created.
2. Each attachment is uploaded to S3.
3. A `mail_item_attachments` row is created for each uploaded object.

## Migration From Local Files

The legacy migration script is:

```text
scripts/migrate_local_files_to_s3.py
```

It walks a local directory and uploads every file into the configured bucket and
prefix.

Example:

```bash
python3 scripts/migrate_local_files_to_s3.py \
  --local-root /data/storage \
  --prefix uploads \
  --bucket postbuch \
  --skip-existing
```

Use `--skip-existing` when rerunning the migration. The script uses
`head_object` to avoid overwriting existing keys.

## Operational Verification

### Check the app configuration

Inside the web container:

```bash
docker compose exec -T web python - <<'PY'
from postbuch.core.config import get_settings
s = get_settings()
print("endpoint:", s.s3_endpoint)
print("region:", s.s3_region)
print("bucket:", s.s3_bucket)
print("prefix:", s.s3_key_prefix)
print("ttl:", s.s3_presigned_url_ttl_seconds)
PY
```

### Upload a test object with boto3

```bash
docker compose exec -T web python - <<'PY'
import io
from postbuch.services.documents import DocumentStoreService

store = DocumentStoreService()
stored = store.store_bytes(
    content=b"postbuch s3 smoke test\n",
    original_filename="s3-smoke-test.txt",
    mime_type="text/plain",
)
print(stored.storage_bucket)
print(stored.storage_key)
print(stored.sha256_hash)
print(store.generate_download_url(
    storage_bucket=stored.storage_bucket,
    storage_key=stored.storage_key,
    original_filename=stored.original_filename,
    mime_type=stored.mime_type,
    expires_in_seconds=60,
))
PY
```

This creates a real object. Delete it afterward if you do not want to keep it.

### Check database references

```sql
SELECT storage_bucket, count(*)
FROM documents
GROUP BY storage_bucket;

SELECT storage_bucket, count(*)
FROM mail_item_attachments
GROUP BY storage_bucket;

SELECT storage_key
FROM documents
ORDER BY id DESC
LIMIT 5;
```

## Backup And Restore

The database and bucket must be backed up together.

The database contains:

- object keys
- original filenames
- hashes
- MIME types
- correspondence relationships

The bucket contains:

- the actual binaries

If you restore only the database, downloads will fail for missing objects. If you
restore only the bucket, the app will not know which objects belong to which
records.

Recommended restore order:

1. Restore PostgreSQL.
2. Restore or keep the S3 bucket contents.
3. Verify `.env` points to the bucket and endpoint.
4. Run migrations.
5. Open several correspondence records and verify downloads.

## Production Migration Note

In the production migration documented in
`docs/operations/production_migration.md`, the bucket stays the same. The prune
script keeps scan-import `documents` and their `storage_key` references. That is
why preserving the same bucket is enough for existing scan-import history.

Old development objects that are no longer referenced by the pruned database
become orphaned. They do not affect the app, but they still consume storage. Use
bucket lifecycle management or a carefully reviewed cleanup script if you want
to delete them later.

## Security Notes

- Keep the bucket private.
- Use presigned URLs instead of public object URLs.
- Treat `POSTBUCH_S3_SECRET_ACCESS_KEY` as a production secret.
- Do not bake `.env` into Docker images.
- Use separate keys for production and development when possible.
- Rotate keys if they are exposed in logs, shell history, screenshots, or
  commits.
- Avoid storing original filenames in S3 object keys; Postbuch stores them only
  in the database and response headers.

## Failure Modes

### `S3 storage is not fully configured`

One or more required `POSTBUCH_S3_*` variables is missing.

### `SignatureDoesNotMatch`

Common causes:

- wrong secret key
- wrong endpoint/region combination
- using a key from a different Hetzner project
- clock skew on the server

### `NoSuchBucket`

The bucket name is wrong, the bucket is in a different location, or the access
key belongs to a project that cannot see the bucket.

### Presigned URL returns 403

Common causes:

- expired URL
- object key is wrong
- bucket/key was deleted
- credentials used to sign the URL no longer have access

### Downloads work locally but not in production

Check:

- production `.env`
- endpoint and region
- whether `storage_bucket` in old rows matches the bucket still in use
- whether old objects were copied or preserved during migration

## Reusable Kit

See:

```text
kits/hetzner_s3_kit/
```

The kit contains standalone example code for:

- creating a Hetzner S3 client
- uploading bytes
- generating presigned download URLs
- checking object existence
- migrating a local directory into a bucket
- testing configuration from environment variables

