from __future__ import annotations

import re
import secrets
import unicodedata
from pathlib import Path


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return slug or "unbenannt"


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)

