#!/usr/bin/env python
"""Seed a realistic but entirely fictional Postbuch dataset.

Every name, address, sender and document reference below is invented. Nothing
here corresponds to a real person or organisation — the point is to give a fresh
checkout something to look at without needing a real mailbox.

    docker compose run --rm web python scripts/seed_demo_data.py
    docker compose run --rm web python scripts/seed_demo_data.py --reset

``--reset`` deletes the rows this script creates before re-inserting them. It
touches only demo rows (matched by the marker below), never anything else.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Running `python scripts/seed_demo_data.py` puts scripts/ on sys.path rather
# than the project root, so the postbuch package would not be importable.
# Prepend the repo root so the script works however it is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from postbuch.db.session import SessionLocal  # noqa: E402
from postbuch.models.category import Category  # noqa: E402
from postbuch.models.correspondence import Correspondence  # noqa: E402
from postbuch.models.enums import (
    CorrespondenceStatus,
    Direction,
    OCRStatus,
    Role,
    SourceType,
)
from postbuch.models.user import User  # noqa: E402

# Every seeded correspondence carries this in `notes`, so --reset can find
# exactly what it created and nothing else.
DEMO_MARKER = "[demo-data]"

DEMO_USERS = [
    ("admin@example.com", "Demo Admin", Role.SUPER_ADMIN),
    ("editor@example.com", "Erika Beispiel", Role.EDITOR),
    ("viewer@example.com", "Viktor Muster", Role.VIEWER),
]

DEMO_CATEGORIES = [
    ("Behörden", "behoerden", "Correspondence with public authorities"),
    ("Finanzen", "finanzen", "Invoices, bank statements, tax matters"),
    ("Personal", "personal", "Employment and HR correspondence"),
    ("Verträge", "vertraege", "Contracts and their amendments"),
    ("Sonstiges", "sonstiges", "Anything that fits nowhere else"),
]

# (days_ago, direction, title, category_slug, status, source, from, subject)
DEMO_CORRESPONDENCE = [
    (2, Direction.INCOMING, "Bescheid über Grundsteuer 2026", "behoerden",
     CorrespondenceStatus.NEW, SourceType.EMAIL_IMPORT,
     "finanzamt@example.gov", "Grundsteuerbescheid 2026"),
    (3, Direction.INCOMING, "Rechnung Nr. 2026-0417 — Musterdruck GmbH", "finanzen",
     CorrespondenceStatus.IN_PROGRESS, SourceType.EMAIL_IMPORT,
     "rechnung@musterdruck.example", "Ihre Rechnung 2026-0417"),
    (5, Direction.OUTGOING, "Kündigung Wartungsvertrag Aufzug", "vertraege",
     CorrespondenceStatus.DONE, SourceType.MANUAL_ENTRY, None, None),
    (8, Direction.INCOMING, "Arbeitsvertrag — Rückläufer unterschrieben", "personal",
     CorrespondenceStatus.DONE, SourceType.MANUAL_UPLOAD, None, None),
    (9, Direction.INCOMING, "Mahnung Stadtwerke — Kundennr. 88231", "finanzen",
     CorrespondenceStatus.IN_PROGRESS, SourceType.EMAIL_IMPORT,
     "mahnwesen@stadtwerke.example", "Zahlungserinnerung"),
    (12, Direction.OUTGOING, "Widerspruch gegen Gebührenbescheid", "behoerden",
     CorrespondenceStatus.IN_PROGRESS, SourceType.MANUAL_ENTRY, None, None),
    (14, Direction.INCOMING, "Versicherungspolice — Verlängerung 2027", "vertraege",
     CorrespondenceStatus.NEW, SourceType.MANUAL_UPLOAD, None, None),
    (18, Direction.INCOMING, "Einladung Mitgliederversammlung", "sonstiges",
     CorrespondenceStatus.DONE, SourceType.EMAIL_IMPORT,
     "vorstand@musterverein.example", "Einladung zur Mitgliederversammlung"),
    (21, Direction.OUTGOING, "Antwort auf Anfrage Raumnutzung", "sonstiges",
     CorrespondenceStatus.DONE, SourceType.MANUAL_ENTRY, None, None),
    (25, Direction.INCOMING, "Kontoauszug März 2026", "finanzen",
     CorrespondenceStatus.DONE, SourceType.MANUAL_UPLOAD, None, None),
    (30, Direction.INCOMING, "Betriebskostenabrechnung 2025", "finanzen",
     CorrespondenceStatus.NEW, SourceType.MANUAL_UPLOAD, None, None),
    (33, Direction.OUTGOING, "Bestätigung Praktikumsplatz", "personal",
     CorrespondenceStatus.DONE, SourceType.MANUAL_ENTRY, None, None),
]

SAMPLE_OCR = (
    "Sehr geehrte Damen und Herren,\n\n"
    "hiermit übersenden wir Ihnen die angeforderten Unterlagen zu obigem "
    "Vorgang. Bitte prüfen Sie diese und teilen Sie uns etwaige Rückfragen "
    "innerhalb von 14 Tagen mit.\n\n"
    "Mit freundlichen Grüßen\n"
    "Musterabteilung\n\n"
    "--- Dieser Text ist Beispiel-OCR aus dem Demo-Datensatz. ---"
)


def reset(session) -> int:
    """Delete only the rows this script created."""
    rows = session.scalars(
        select(Correspondence).where(Correspondence.notes.like(f"{DEMO_MARKER}%"))
    ).all()
    for row in rows:
        session.delete(row)
    session.flush()

    session.execute(
        delete(User).where(User.email.in_([email for email, _, _ in DEMO_USERS]))
    )
    session.execute(
        delete(Category).where(Category.slug.in_([slug for _, slug, _ in DEMO_CATEGORIES]))
    )
    session.commit()
    return len(rows)


def seed(session) -> dict:
    counts = {"users": 0, "categories": 0, "correspondence": 0}

    for email, display_name, role in DEMO_USERS:
        if session.scalar(select(User).where(User.email == email)):
            continue
        session.add(
            User(email=email, display_name=display_name, role=role, is_active=True)
        )
        counts["users"] += 1
    session.flush()

    categories: dict[str, Category] = {}
    for name, slug, description in DEMO_CATEGORIES:
        existing = session.scalar(select(Category).where(Category.slug == slug))
        if existing:
            categories[slug] = existing
            continue
        category = Category(
            name=name, slug=slug, description=description, is_active=True
        )
        session.add(category)
        categories[slug] = category
        counts["categories"] += 1
    session.flush()

    today = date.today()
    now = datetime.now(timezone.utc)

    for (
        days_ago, direction, title, category_slug, status, source_type,
        email_from, email_subject,
    ) in DEMO_CORRESPONDENCE:
        entry_date = today - timedelta(days=days_ago)
        is_scan = source_type is SourceType.MANUAL_UPLOAD

        session.add(
            Correspondence(
                direction=direction,
                title=title,
                entry_date=entry_date,
                status=status,
                category_id=categories[category_slug].id,
                notes=f"{DEMO_MARKER} fictional record for demonstration",
                source_type=source_type,
                source_email_from=email_from,
                source_email_to="post@example.org" if email_from else None,
                source_email_subject=email_subject,
                source_email_received_at=(
                    now - timedelta(days=days_ago) if email_from else None
                ),
                source_mailbox="posteingang" if email_from else None,
                # Only scanned uploads carry OCR text; e-mail imports already
                # have machine-readable bodies, which is why the real pipeline
                # marks them NOT_APPLICABLE rather than PENDING.
                ocr_text=SAMPLE_OCR if is_scan else None,
                ocr_status=OCRStatus.COMPLETED if is_scan else OCRStatus.NOT_APPLICABLE,
                ocr_method="tesseract" if is_scan else None,
                ocr_page_count=2 if is_scan else None,
                completion_note=(
                    "Erledigt und abgelegt."
                    if status is CorrespondenceStatus.DONE
                    else None
                ),
            )
        )
        counts["correspondence"] += 1

    session.commit()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete previously seeded demo rows before inserting",
    )
    args = parser.parse_args()

    with SessionLocal() as session:
        if args.reset:
            removed = reset(session)
            print(f"Removed {removed} previously seeded correspondence rows.")

        counts = seed(session)

    print(
        "Demo data seeded: "
        f"{counts['users']} users, "
        f"{counts['categories']} categories, "
        f"{counts['correspondence']} correspondence records."
    )
    print("Log in at /auth/login with the developer form — e.g. admin@example.com")
    return 0


if __name__ == "__main__":
    sys.exit(main())
