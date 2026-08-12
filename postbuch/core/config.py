from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POSTBUCH_", env_file=".env", extra="ignore")

    env: str = "development"
    app_name: str = "Postbuch"
    secret_key: str = "dev-secret-key"
    database_url: str = "postgresql+psycopg://postbuch:postbuch@db:5432/postbuch"
    session_cookie_name: str = "postbuch_session"
    # Legacy local filesystem setting retained only for one-time migration tooling.
    storage_root: Path = Path("var/storage")
    s3_endpoint: str = Field(default="", validation_alias=AliasChoices("POSTBUCH_S3_ENDPOINT", "S3_ENDPOINT"))
    s3_region: str = Field(default="", validation_alias=AliasChoices("POSTBUCH_S3_REGION", "S3_REGION"))
    s3_access_key_id: str = Field(default="", validation_alias=AliasChoices("POSTBUCH_S3_ACCESS_KEY_ID", "S3_ACCESS_KEY_ID"))
    s3_secret_access_key: str = Field(
        default="",
        validation_alias=AliasChoices("POSTBUCH_S3_SECRET_ACCESS_KEY", "S3_SECRET_ACCESS_KEY"),
    )
    s3_bucket: str = Field(default="", validation_alias=AliasChoices("POSTBUCH_S3_BUCKET", "S3_BUCKET"))
    s3_presigned_url_ttl_seconds: int = 3600
    s3_key_prefix: str = "uploads"

    oidc_enabled: bool = True
    oidc_server_metadata_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scopes: str = "openid profile email"
    dev_auth_enabled: bool = False

    imap_poll_seconds: int = 300

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_address: str | None = None
    smtp_use_tls: bool = True

    ocr_language: str = "deu+eng"
    ocr_min_text_length: int = 80


@lru_cache
def get_settings() -> Settings:
    return Settings()
