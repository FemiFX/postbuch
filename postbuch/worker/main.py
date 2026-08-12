from __future__ import annotations

import logging
import time

from postbuch.core.config import get_settings
from postbuch.db.session import SessionLocal
from postbuch.services.imports import run_import_cycle

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    settings = get_settings()
    logger.info("Starting Postbuch worker")
    while True:
        db = SessionLocal()
        try:
            runs = run_import_cycle(db)
            logger.info("Completed import cycle for %s mailbox(es)", len(runs))
        except Exception as exc:  # pragma: no cover
            logger.exception("Worker cycle failed: %s", exc)
        finally:
            db.close()
        time.sleep(settings.imap_poll_seconds)


if __name__ == "__main__":
    main()
