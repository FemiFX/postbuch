from __future__ import annotations

import argparse
import mimetypes
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from postbuch.core.config import get_settings


def build_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4"),
    )


def object_exists(client, *, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        error_code = (exc.response.get("Error") or {}).get("Code")
        if error_code in {"404", "NoSuchKey"}:
            return False
        raise
    return True


def upload_directory(
    *,
    local_root: Path,
    bucket: str,
    prefix: str,
    skip_existing: bool,
) -> tuple[int, int]:
    client = build_client()
    uploaded = 0
    skipped = 0
    normalized_prefix = prefix.strip("/")

    for file_path in local_root.rglob("*"):
        if not file_path.is_file():
            continue

        relative = file_path.relative_to(local_root).as_posix()
        key = f"{normalized_prefix}/{relative}" if normalized_prefix else relative

        if skip_existing and object_exists(client, bucket=bucket, key=key):
            skipped += 1
            continue

        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        with file_path.open("rb") as file_data:
            client.upload_fileobj(
                file_data,
                Bucket=bucket,
                Key=key,
                ExtraArgs={"ContentType": mime_type},
            )
        uploaded += 1
        print(f"uploaded {file_path} -> s3://{bucket}/{key}")

    return uploaded, skipped


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Upload legacy local files into configured S3 storage.")
    parser.add_argument(
        "--local-root",
        type=Path,
        default=settings.storage_root,
        help="Local directory containing legacy files (default: POSTBUCH_STORAGE_ROOT).",
    )
    parser.add_argument(
        "--prefix",
        default=settings.s3_key_prefix,
        help="Object key prefix in bucket (default: POSTBUCH_S3_KEY_PREFIX).",
    )
    parser.add_argument(
        "--bucket",
        default=settings.s3_bucket,
        help="Target bucket (default: POSTBUCH_S3_BUCKET).",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip files that already exist at the destination key.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.local_root.exists():
        raise SystemExit(f"Local root does not exist: {args.local_root}")
    if not args.local_root.is_dir():
        raise SystemExit(f"Local root is not a directory: {args.local_root}")
    if not args.bucket:
        raise SystemExit("Missing target bucket. Set --bucket or POSTBUCH_S3_BUCKET.")

    uploaded, skipped = upload_directory(
        local_root=args.local_root,
        bucket=args.bucket,
        prefix=args.prefix,
        skip_existing=args.skip_existing,
    )
    print(f"done: uploaded={uploaded} skipped={skipped}")


if __name__ == "__main__":
    main()
