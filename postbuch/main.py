from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from postbuch.api.routes import router
from postbuch.core.config import get_settings
from postbuch.core.templating import templates
from postbuch.db.session import SessionLocal
from postbuch.models.user import User


logging.basicConfig(
    level=logging.DEBUG if get_settings().env != "production" else logging.WARNING,
    format="%(levelname)s [%(name)s] %(message)s",
)

settings = get_settings()
app = FastAPI(title=settings.app_name)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie=settings.session_cookie_name,
    same_site="lax",
    https_only=False,
)
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")
app.include_router(router)


def _friendly_error(exc: Exception) -> tuple[str, int]:
    """Return (user-facing message, HTTP status code) for a given exception."""
    if isinstance(exc, HTTPException):
        status_messages = {
            400: "Ungültige Anfrage.",
            401: "Anmeldung erforderlich.",
            403: "Sie haben keine Berechtigung für diese Aktion.",
            404: "Die angeforderte Seite wurde nicht gefunden.",
            409: "Ein Eintrag mit diesen Daten existiert bereits.",
        }
        return status_messages.get(exc.status_code, exc.detail), exc.status_code

    if isinstance(exc, IntegrityError):
        orig = str(getattr(exc, "orig", "") or "").lower()
        if "unique" in orig or "duplicate" in orig:
            return "Ein Eintrag mit diesen Daten existiert bereits. Bitte überprüfen Sie die Eingabe.", 409
        return "Ein Datenbankfehler ist aufgetreten. Bitte versuchen Sie es erneut.", 500

    return "Ein unerwarteter Fehler ist aufgetreten. Bitte versuchen Sie es erneut.", 500


def _try_get_user(request: Request) -> User | None:
    try:
        user_id = request.session.get("user_id")
        if not user_id:
            return None
        with SessionLocal() as db:
            user = db.get(User, user_id)
            return user if user and user.is_active else None
    except Exception:
        return None


def _wants_json(request: Request) -> bool:
    if request.url.path.startswith("/api/") or request.url.path.startswith("/admin/api/"):
        return True
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return False
    if "application/json" in accept:
        return True
    return False


def _render_error(request: Request, *, message: str, status_code: int):
    current_user = _try_get_user(request)
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "request": request,
            "message": message,
            "current_user": current_user,
            "nav_triage_count": 0,
            "nav_duplicate_count": 0,
            "nav_proposal_count": 0,
            "csrf_token": request.session.get("csrf_token", ""),
        },
        status_code=status_code,
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == status.HTTP_401_UNAUTHORIZED and not _wants_json(request):
        params = urlencode({"notice": "Bitte melden Sie sich an, um fortzufahren."})
        return RedirectResponse(url=f"/auth/login?{params}", status_code=status.HTTP_303_SEE_OTHER)
    if _wants_json(request):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    message, status_code = _friendly_error(exc)
    return _render_error(request, message=message, status_code=status_code)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    message, status_code = _friendly_error(exc)
    if _wants_json(request):
        return JSONResponse({"detail": message}, status_code=status_code)
    return _render_error(request, message=message, status_code=status_code)
