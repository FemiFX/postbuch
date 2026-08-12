from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone
from uuid import uuid4

import boto3
from botocore.client import Config
from fastapi import UploadFile

from postbuch.core.config import get_settings


class StoredDocument:
    def __init__(
        self,
        *,
        storage_bucket: str,
        storage_key: str,
        original_filename: str,
        mime_type: str,
        file_size_bytes: int,
        sha256_hash: str,
    ):
        self.storage_bucket = storage_bucket
        self.storage_key = storage_key
        self.original_filename = original_filename
        self.mime_type = mime_type
        self.file_size_bytes = file_size_bytes
        self.sha256_hash = sha256_hash
        self.stored_filename = storage_key.rsplit("/", 1)[-1]


class DocumentStoreService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._s3_client = None

    def _validate_s3_config(self) -> None:
        required_values = {
            "s3_endpoint": self.settings.s3_endpoint,
            "s3_region": self.settings.s3_region,
            "s3_access_key_id": self.settings.s3_access_key_id,
            "s3_secret_access_key": self.settings.s3_secret_access_key,
            "s3_bucket": self.settings.s3_bucket,
        }
        missing = [key for key, value in required_values.items() if not value]
        if missing:
            raise RuntimeError(f"S3 storage is not fully configured. Missing: {', '.join(missing)}")

    def _client(self):
        if self._s3_client is not None:
            return self._s3_client
        self._validate_s3_config()
        self._s3_client = boto3.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint,
            aws_access_key_id=self.settings.s3_access_key_id,
            aws_secret_access_key=self.settings.s3_secret_access_key,
            region_name=self.settings.s3_region,
            config=Config(signature_version="s3v4"),
        )
        return self._s3_client

    def _build_storage_key(self, original_filename: str) -> str:
        suffix = ""
        if "." in original_filename:
            suffix = f".{original_filename.rsplit('.', 1)[-1].lower()}"
        elif not original_filename:
            suffix = ".bin"

        now = datetime.now(timezone.utc)
        prefix = self.settings.s3_key_prefix.strip("/")
        date_path = f"{now:%Y/%m}"
        if prefix:
            return f"{prefix}/{date_path}/{uuid4().hex}{suffix}"
        return f"{date_path}/{uuid4().hex}{suffix}"

    def _write_bytes(self, *, content: bytes, original_filename: str, mime_type: str) -> StoredDocument:
        storage_key = self._build_storage_key(original_filename)
        bucket = self.settings.s3_bucket
        self._client().upload_fileobj(
            Fileobj=io.BytesIO(content),
            Bucket=bucket,
            Key=storage_key,
            ExtraArgs={"ContentType": mime_type or "application/octet-stream"},
        )
        digest = hashlib.sha256(content).hexdigest()
        return StoredDocument(
            storage_bucket=bucket,
            storage_key=storage_key,
            original_filename=original_filename,
            mime_type=mime_type or "application/octet-stream",
            file_size_bytes=len(content),
            sha256_hash=digest,
        )

    async def store_upload(self, upload: UploadFile) -> StoredDocument:
        content = await upload.read()
        return self._write_bytes(
            content=content,
            original_filename=upload.filename or "upload.bin",
            mime_type=upload.content_type or "application/octet-stream",
        )

    def store_bytes(self, *, content: bytes, original_filename: str, mime_type: str) -> StoredDocument:
        return self._write_bytes(content=content, original_filename=original_filename, mime_type=mime_type)

    def generate_download_url(
        self,
        *,
        storage_key: str,
        original_filename: str,
        mime_type: str | None = None,
        inline: bool = False,
        storage_bucket: str | None = None,
        expires_in_seconds: int | None = None,
    ) -> str:
        bucket = storage_bucket or self.settings.s3_bucket
        if not bucket:
            raise RuntimeError("Missing storage bucket for document download.")
        disposition = "inline" if inline else "attachment"
        safe_filename = original_filename.replace('"', "_").replace("\n", "_").replace("\r", "_")
        params = {
            "Bucket": bucket,
            "Key": storage_key,
            "ResponseContentDisposition": f'{disposition}; filename="{safe_filename}"',
        }
        if mime_type:
            params["ResponseContentType"] = mime_type
        return self._client().generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expires_in_seconds or self.settings.s3_presigned_url_ttl_seconds,
        )
