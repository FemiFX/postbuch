from __future__ import annotations

import csv
import json
import logging
from datetime import date, datetime, timezone
from email.utils import parseaddr
from io import StringIO
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import distinct, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from postbuch.api.deps import get_current_user, get_optional_user, require_role, verify_csrf
from postbuch.auth.oidc import authorize_redirect, fetch_userinfo
from postbuch.core.config import get_settings
from postbuch.core.templating import templates
from postbuch.core.utils import generate_csrf_token
from postbuch.db.session import get_db
from postbuch.models.audit_log import AuditLog
from postbuch.models.category import Category
from postbuch.models.category_proposal import CategoryProposal
from postbuch.models.correspondence import Correspondence
from postbuch.models.document import Document
from postbuch.models.email_case import EmailCase
from postbuch.models.email_case_event import EmailCaseEvent
from postbuch.models.email_message import EmailMessage
from postbuch.models.enums import (
    CorrespondenceStatus,
    Direction,
    MailItemActionType,
    MailItemStatus,
    MailboxProcessingMode,
    Role,
    SourceType,
)
from postbuch.models.forwarding_route import ForwardingRoute
from postbuch.models.forwarding_template import ForwardingTemplate
from postbuch.models.mail_item import MailItem
from postbuch.models.mail_item_attachment import MailItemAttachment
from postbuch.models.import_run import ImportRun
from postbuch.models.mailbox import Mailbox
from postbuch.models.smtp_config import SmtpConfig
from postbuch.models.user import User
from postbuch.schemas.category import CategoryCreate, CategoryProposalCreate, CategoryProposalRead, CategoryRead
from postbuch.schemas.common import AuditLogRead
from postbuch.schemas.correspondence import (
    CorrespondenceCreate,
    CorrespondenceDirectionUpdate,
    CorrespondenceFilter,
    CorrespondenceRead,
    CorrespondenceStatusUpdate,
    CorrespondenceUpdate,
)
from postbuch.schemas.forwarding import (
    ForwardActionPayload,
    ForwardingRouteCreate,
    ForwardingRouteRead,
    ForwardingRouteUpdate,
    ForwardingTemplateCreate,
    ForwardingTemplateRead,
    ForwardingTemplateUpdate,
)
from postbuch.services.email_sender import render_default_forward, render_template as render_fwd_template, send_forward_email
from postbuch.schemas.imports import EmailMessageRead, ImportRunRead
from postbuch.schemas.mailbox import MailboxCreate, MailboxRead, MailboxUpdate
from postbuch.schemas.mail_items import (
    MailItemAssignCategory,
    MailItemAttachmentRead,
    MailItemFilter,
    MailItemNoteCreate,
    MailItemNoteRead,
    MailItemRead,
    MailItemTimelineEventRead,
    MailItemUpdate,
)
from postbuch.schemas.user import TriageAssigneeRead, UserActiveUpdate, UserCreate, UserRead, UserRoleUpdate, UserUpdate
from postbuch.schemas.email_case import EmailCaseDetailRead
from postbuch.services.audit import (
    audit_login_failed,
    audit_login_success,
    audit_logout,
    create_audit_entry,
)
from postbuch.services.categories import create_category, create_proposal, list_categories, review_proposal
from postbuch.services.correspondence import (
    count_assigned_items,
    create_manual_correspondence,
    dashboard_counts,
    list_audit_entries,
    list_correspondence,
    move_direction,
    transition_status,
    update_correspondence,
)
from postbuch.services.documents import DocumentStoreService
from postbuch.services.imports import IMAPPollService, perform_imap_writeback, run_import_cycle
from postbuch.services.mail_item_workflow import (
    add_mail_item_note,
    close_mail_item,
    get_mail_item_timeline,
    list_mail_item_notes,
    list_mail_items_for_triage,
    mark_mail_item_spam,
    record_forward_decision,
    update_mail_item_from_patch,
)
from postbuch.services.users import (
    OIDCLoginError,
    OIDCUserInfo,
    create_user,
    provision_dev_user,
    provision_oidc_preapproved_user,
    update_user,
    update_user_active,
    update_user_role,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_effective_smtp(db: Session) -> dict:
    """Return SMTP settings from the DB row (id=1) if smtp_host is set, else from env."""
    cfg = db.get(SmtpConfig, 1)
    if cfg and cfg.smtp_host:
        return {
            "host": cfg.smtp_host,
            "port": cfg.smtp_port,
            "username": cfg.smtp_username,
            "password": cfg.smtp_password,
            "from_address": cfg.smtp_from_address,
            "use_tls": cfg.smtp_use_tls,
        }
    s = get_settings()
    return {
        "host": s.smtp_host,
        "port": s.smtp_port,
        "username": s.smtp_username,
        "password": s.smtp_password,
        "from_address": s.smtp_from_address,
        "use_tls": s.smtp_use_tls,
    }


def _nav_counts(db: Session, *, current_user_id: int | None = None) -> dict[str, int]:
    from postbuch.models.enums import CorrespondenceStatus
    email_incoming_count = db.scalar(select(func.count(MailItem.id)).where(MailItem.status == MailItemStatus.NEW)) or 0
    paper_incoming_count = db.scalar(
        select(func.count(Correspondence.id))
        .where(Correspondence.direction == Direction.INCOMING, Correspondence.status == CorrespondenceStatus.NEW)
    ) or 0
    paper_outgoing_count = db.scalar(
        select(func.count(Correspondence.id))
        .where(Correspondence.direction == Direction.OUTGOING, Correspondence.status == CorrespondenceStatus.NEW)
    ) or 0
    assigned_count = 0
    if current_user_id is not None:
        assigned_count = db.scalar(
            select(func.count(MailItem.id)).where(
                MailItem.assigned_to_user_id == current_user_id,
                MailItem.status.not_in([
                    MailItemStatus.CLOSED,
                    MailItemStatus.SPAM,
                    MailItemStatus.ERROR,
                ]),
            )
        ) or 0
    return {
        "nav_triage_count": int(email_incoming_count + paper_incoming_count + paper_outgoing_count),
        "nav_duplicate_count": db.scalar(select(func.count(Correspondence.id)).where(Correspondence.is_duplicate_flag.is_(True))) or 0,
        "nav_proposal_count": db.scalar(select(func.count(CategoryProposal.id)).where(CategoryProposal.status == "pending")) or 0,
        "nav_paper_incoming_count": int(paper_incoming_count),
        "nav_paper_outgoing_count": int(paper_outgoing_count),
        "nav_email_incoming_count": int(email_incoming_count),
        "nav_assigned_count": int(assigned_count),
    }


_EMAIL_OPEN_STATUSES: list[MailItemStatus] = [
    MailItemStatus.NEW,
    MailItemStatus.IN_PROGRESS,
    MailItemStatus.WAITING,
    MailItemStatus.FORWARDED,
    MailItemStatus.REPLIED,
    MailItemStatus.ERROR,
]
_EMAIL_CLOSED_STATUSES: list[MailItemStatus] = [MailItemStatus.CLOSED, MailItemStatus.SPAM]


def _email_status_counts(
    db: Session,
    *,
    assigned_filter: str = "all",
    assignee_id: int | None = None,
    category_id: int | None = None,
    query_text: str | None = None,
) -> dict[str, int]:
    query_text = (query_text or "").strip() or None

    def _apply_common(stmt):
        if category_id is not None:
            stmt = stmt.where(MailItem.category_id == category_id)
        if query_text:
            like = f"%{query_text}%"
            stmt = stmt.where(
                or_(
                    MailItem.subject.ilike(like),
                    MailItem.body_text.ilike(like),
                    MailItem.sender.ilike(like),
                )
            )
        return stmt

    def _count(statuses: list[MailItemStatus] | None) -> int:
        stmt = select(func.count(MailItem.id))
        if statuses is not None:
            stmt = stmt.where(MailItem.status.in_(statuses))
        if assigned_filter == "unassigned":
            stmt = stmt.where(MailItem.assigned_to_user_id.is_(None))
        elif assigned_filter.startswith("user:") and assignee_id is not None:
            stmt = stmt.where(MailItem.assigned_to_user_id == assignee_id)
        stmt = _apply_common(stmt)
        return int(db.scalar(stmt) or 0)

    return {
        "open": _count(_EMAIL_OPEN_STATUSES),
        "all": _count(None),
        "closed": _count(_EMAIL_CLOSED_STATUSES),
    }


def _priority_from_category_name(category_name: str | None) -> dict[str, str] | None:
    if not category_name:
        return None
    normalized = category_name.strip().lower()
    if any(token in normalized for token in ("urgent", "kritisch", "krit")):
        return {"label": "URGENT", "chip_class": "chip-urgent"}
    if any(token in normalized for token in ("high", "hoch")):
        return {"label": "HIGH", "chip_class": "chip-high"}
    if any(token in normalized for token in ("low", "niedrig")):
        return {"label": "LOW", "chip_class": "chip-low"}
    return None


def template_context(request: Request, db: Session | None = None, **kwargs: Any) -> dict[str, Any]:
    context = {"request": request, **kwargs}
    context["csrf_token"] = request.session.setdefault("csrf_token", generate_csrf_token())
    if db is not None:
        cu = kwargs.get("current_user")
        context.update(_nav_counts(db, current_user_id=cu.id if cu else None))
    else:
        context.update({
            "nav_triage_count": 0, "nav_duplicate_count": 0, "nav_proposal_count": 0,
            "nav_paper_incoming_count": 0, "nav_paper_outgoing_count": 0,
            "nav_email_incoming_count": 0, "nav_assigned_count": 0,
        })
    return context


def get_document_store() -> DocumentStoreService:
    return DocumentStoreService()


def dev_auth_allowed() -> bool:
    settings = get_settings()
    return settings.dev_auth_enabled and settings.env != "production"


def _safe_return_to(value: str | None) -> str | None:
    """Allow only same-origin relative paths as redirect targets."""
    if not value:
        return None
    if not value.startswith("/") or value.startswith("//"):
        return None
    return value


def _friendly_auth_error(message: str | None) -> str:
    if not message:
        return "Anmeldung fehlgeschlagen. Bitte versuchen Sie es erneut."
    normalized = message.strip()
    mapping = {
        "OIDC response missing subject.": "OIDC-Antwort enthält keine gültige Benutzerkennung.",
        "OIDC response missing email.": "OIDC-Antwort enthält keine E-Mail-Adresse.",
        "User is not pre-approved for OIDC login.": "Ihr Konto ist für OIDC nicht freigeschaltet.",
        "User is inactive.": "Ihr Benutzerkonto ist inaktiv.",
        "OIDC subject mismatch.": "OIDC-Anmeldung passt nicht zum freigegebenen Benutzerkonto.",
        "OIDC issuer mismatch.": "OIDC-Anbieter stimmt nicht mit dem Benutzerkonto überein.",
    }
    return mapping.get(normalized, normalized)


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), current_user: User | None = Depends(get_optional_user)):
    if current_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    counts = dashboard_counts(db)
    assigned_count = count_assigned_items(db, current_user.id, active_only=True)
    pending_proposals = (
        int(db.scalar(select(func.count(CategoryProposal.id)).where(CategoryProposal.status == "pending")) or 0)
        if current_user.role == Role.SUPER_ADMIN
        else 0
    )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        template_context(request, db=db, current_user=current_user, counts=counts,
                         pending_proposals=pending_proposals, assigned_count=assigned_count),
    )


@router.get("/auth/login", name="auth_login", response_class=HTMLResponse)
async def auth_login_page(
    request: Request,
    error: str | None = None,
    notice: str | None = None,
    logged_out: bool = False,
):
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        template_context(
            request,
            current_user=None,
            oidc_enabled=settings.oidc_enabled,
            dev_auth_enabled=dev_auth_allowed(),
            roles=[role.value for role in Role],
            auth_error=error,
            auth_notice=notice,
            auth_form={
                "display_name": "Local Admin",
                "email": "admin@example.com",
                "role": Role.SUPER_ADMIN.value,
            },
        ),
    )


@router.get("/auth/oidc")
async def auth_oidc(request: Request):
    try:
        return await authorize_redirect(request)
    except Exception:
        logger.exception("OIDC authorize redirect failed from /auth/oidc")
        params = urlencode({"error": "Verbindung zum OIDC-Anbieter fehlgeschlagen. Bitte prüfen Sie die OIDC-Konfiguration."})
        return RedirectResponse(url=f"/auth/login?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    try:
        oidc_data = await fetch_userinfo(request)
        userinfo = oidc_data.get("userinfo") or {}
        display_name = userinfo.get("name") or userinfo.get("preferred_username") or userinfo.get("email") or "User"
        oidc = OIDCUserInfo(
            subject=userinfo.get("sub"),
            issuer=userinfo.get("iss"),
            email=userinfo.get("email"),
            display_name=display_name,
        )
        user = provision_oidc_preapproved_user(db, oidc=oidc)
    except OIDCLoginError as exc:
        params = urlencode({"error": _friendly_auth_error(exc.message)})
        return RedirectResponse(url=f"/auth/login?{params}", status_code=status.HTTP_303_SEE_OTHER)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else None
        params = urlencode({"error": _friendly_auth_error(detail)})
        return RedirectResponse(url=f"/auth/login?{params}", status_code=status.HTTP_303_SEE_OTHER)
    except Exception:
        logger.exception("OIDC callback failed")
        params = urlencode({"error": "Ein unerwarteter Fehler ist aufgetreten. Bitte versuchen Sie es erneut."})
        return RedirectResponse(url=f"/auth/login?{params}", status_code=status.HTTP_303_SEE_OTHER)

    audit_login_success(db, user)
    db.commit()
    request.session["user_id"] = user.id
    request.session.setdefault("csrf_token", generate_csrf_token())
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/auth/logout", dependencies=[Depends(verify_csrf)])
def auth_logout(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if user_id:
        user = db.get(User, user_id)
        if user is not None:
            audit_logout(db, user)
            db.commit()
    request.session.clear()
    return RedirectResponse(url="/auth/login?logged_out=1", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/auth/dev-login", dependencies=[Depends(verify_csrf)])
def auth_dev_login(
    request: Request,
    email: str | None = Form(default=None),
    display_name: str = Form(...),
    role: Role = Form(default=Role.SUPER_ADMIN),
    db: Session = Depends(get_db),
):
    if not dev_auth_allowed():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    cleaned_email = email.strip() if email else ""
    cleaned_display_name = display_name.strip()
    try:
        user = provision_dev_user(
            db,
            email=cleaned_email or None,
            display_name=cleaned_display_name,
            role=role,
        )
    except IntegrityError:
        # Roll back first. The failed flush leaves the session in a pending-
        # rollback state, so writing the audit entry and committing on the same
        # session raises PendingRollbackError and turns this handled error into
        # an unhandled 500.
        db.rollback()
        audit_login_failed(db, email=cleaned_email or None, reason="dev_login_integrity_error")
        db.commit()
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            template_context(
                request,
                current_user=None,
                oidc_enabled=get_settings().oidc_enabled,
                dev_auth_enabled=dev_auth_allowed(),
                roles=[known_role.value for known_role in Role],
                auth_error="Lokale Anmeldung fehlgeschlagen. Bitte prüfen Sie Anzeigename und E-Mail.",
                auth_form={
                    "display_name": cleaned_display_name or "Local Admin",
                    "email": cleaned_email,
                    "role": role.value,
                },
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except ValueError as exc:
        audit_login_failed(db, email=cleaned_email or None, reason=str(exc))
        db.commit()
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            template_context(
                request,
                current_user=None,
                oidc_enabled=get_settings().oidc_enabled,
                dev_auth_enabled=dev_auth_allowed(),
                roles=[known_role.value for known_role in Role],
                auth_error=_friendly_auth_error(str(exc)),
                auth_form={
                    "display_name": cleaned_display_name or "Local Admin",
                    "email": cleaned_email,
                    "role": role.value,
                },
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        audit_login_failed(db, email=cleaned_email or None, reason="dev_login_unexpected_error")
        db.commit()
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            template_context(
                request,
                current_user=None,
                oidc_enabled=get_settings().oidc_enabled,
                dev_auth_enabled=dev_auth_allowed(),
                roles=[known_role.value for known_role in Role],
                auth_error="Ein unerwarteter Fehler ist aufgetreten. Bitte versuchen Sie es erneut.",
                auth_form={
                    "display_name": cleaned_display_name or "Local Admin",
                    "email": cleaned_email,
                    "role": role.value,
                },
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    audit_login_success(db, user)
    db.commit()
    request.session["user_id"] = user.id
    request.session.setdefault("csrf_token", generate_csrf_token())
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/api/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.get("/api/nav-counts")
def api_nav_counts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _nav_counts(db, current_user_id=current_user.id)


@router.get("/mir-zugewiesen", response_class=HTMLResponse)
def assigned_items_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status_filter: str | None = None,
    q: str | None = None,
):
    """Page listing MailItems assigned to the current user."""
    normalized_filter = (status_filter or "active").strip().lower()
    if normalized_filter not in ("active", "all", "closed"):
        normalized_filter = "active"

    closed_statuses = [MailItemStatus.CLOSED, MailItemStatus.SPAM, MailItemStatus.ERROR]
    active_statuses = [s for s in MailItemStatus if s not in closed_statuses]

    stmt = (
        select(MailItem)
        .where(MailItem.assigned_to_user_id == current_user.id)
        .order_by(MailItem.received_at.desc().nulls_last(), MailItem.created_at.desc())
    )
    if normalized_filter == "active":
        stmt = stmt.where(MailItem.status.in_(active_statuses))
    elif normalized_filter == "closed":
        stmt = stmt.where(MailItem.status.in_(closed_statuses))

    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                MailItem.subject.ilike(like),
                MailItem.sender.ilike(like),
                MailItem.body_text.ilike(like),
            )
        )

    items = list(db.scalars(stmt).unique())

    category_ids = {i.category_id for i in items if i.category_id is not None}
    category_map = (
        {c.id: c for c in db.scalars(select(Category).where(Category.id.in_(category_ids)))}
        if category_ids else {}
    )

    return templates.TemplateResponse(
        request,
        "assigned/list.html",
        template_context(
            request,
            db=db,
            current_user=current_user,
            items=items,
            category_map=category_map,
            filters={"status_filter": normalized_filter, "q": (q or "").strip()},
        ),
    )


@router.get("/api/me/assigned-items")
def api_my_assigned_items(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status_filter: str | None = None,
    q: str | None = None,
):
    """API endpoint returning MailItems assigned to the current user."""
    normalized_filter = (status_filter or "active").strip().lower()
    if normalized_filter not in ("active", "all", "closed"):
        normalized_filter = "active"

    closed_statuses = [MailItemStatus.CLOSED, MailItemStatus.SPAM, MailItemStatus.ERROR]
    active_statuses = [s for s in MailItemStatus if s not in closed_statuses]

    stmt = (
        select(MailItem)
        .where(MailItem.assigned_to_user_id == current_user.id)
        .order_by(MailItem.received_at.desc().nulls_last(), MailItem.created_at.desc())
    )
    if normalized_filter == "active":
        stmt = stmt.where(MailItem.status.in_(active_statuses))
    elif normalized_filter == "closed":
        stmt = stmt.where(MailItem.status.in_(closed_statuses))

    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                MailItem.subject.ilike(like),
                MailItem.sender.ilike(like),
                MailItem.body_text.ilike(like),
            )
        )

    return list(db.scalars(stmt).unique())


@router.get("/api/mail-items/status-counts")
def api_mail_items_status_counts(
    assigned_filter: str = "all",
    assignee_id: int | None = None,
    category_id: int | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return _email_status_counts(
        db,
        assigned_filter=assigned_filter,
        assignee_id=assignee_id,
        category_id=category_id,
        query_text=q,
    )


@router.get("/correspondence", response_class=HTMLResponse)
def correspondence_page_redirect(request: Request):
    # Keep backward-compat: redirect old /correspondence to /register
    qs = request.url.query
    url = "/register" + (f"?{qs}" if qs else "")
    return RedirectResponse(url=url, status_code=status.HTTP_301_MOVED_PERMANENTLY)


_MAIL_STATUS_TO_REGISTER: dict[MailItemStatus, str] = {
    MailItemStatus.NEW: "neu",
    MailItemStatus.IN_PROGRESS: "in_bearbeitung",
    MailItemStatus.WAITING: "in_bearbeitung",
    MailItemStatus.FORWARDED: "in_bearbeitung",
    MailItemStatus.REPLIED: "in_bearbeitung",
    MailItemStatus.ERROR: "in_bearbeitung",
    MailItemStatus.CLOSED: "erledigt",
    MailItemStatus.SPAM: "erledigt",
}


def _build_mail_item_register_rows(
    db: Session,
    *,
    query: str | None,
    status_filter: str | None,
    category_id: int | None,
    source_mailbox: str | None,
) -> list[Any]:
    from types import SimpleNamespace

    stmt = select(MailItem)
    if category_id is not None:
        stmt = stmt.where(MailItem.category_id == category_id)
    if query:
        like = f"%{query.strip()}%"
        stmt = stmt.where(
            or_(
                MailItem.subject.ilike(like),
                MailItem.body_text.ilike(like),
                MailItem.sender.ilike(like),
            )
        )
    if status_filter == "neu":
        stmt = stmt.where(MailItem.status == MailItemStatus.NEW)
    elif status_filter == "in_bearbeitung":
        stmt = stmt.where(MailItem.status.in_([
            MailItemStatus.IN_PROGRESS,
            MailItemStatus.WAITING,
            MailItemStatus.FORWARDED,
            MailItemStatus.REPLIED,
            MailItemStatus.ERROR,
        ]))
    elif status_filter == "erledigt":
        stmt = stmt.where(MailItem.status.in_([MailItemStatus.CLOSED, MailItemStatus.SPAM]))
    if source_mailbox:
        stmt = stmt.join(Mailbox, Mailbox.id == MailItem.mailbox_id).where(Mailbox.name == source_mailbox)
    items = list(db.scalars(stmt).unique())

    mailbox_ids = {item.mailbox_id for item in items}
    mailbox_names = (
        {m.id: m.name for m in db.scalars(select(Mailbox).where(Mailbox.id.in_(mailbox_ids)))}
        if mailbox_ids else {}
    )
    category_ids = {item.category_id for item in items if item.category_id is not None}
    category_map = (
        {c.id: c for c in db.scalars(select(Category).where(Category.id.in_(category_ids)))}
        if category_ids else {}
    )

    rows: list[Any] = []
    for item in items:
        received = item.received_at or item.created_at
        rows.append(SimpleNamespace(
            id=item.id,
            entry_date=received.date() if hasattr(received, "date") else received,
            sort_key=received,
            direction="incoming",
            title=item.subject,
            category=category_map.get(item.category_id),
            is_duplicate_flag=False,
            status=_MAIL_STATUS_TO_REGISTER.get(item.status, "in_bearbeitung"),
            source_mailbox=mailbox_names.get(item.mailbox_id),
            source_type="E-Mail",
            detail_url=f"/channels/email-incoming?selected_id={item.id}",
        ))
    return rows


def _wrap_correspondence_row(item):
    from types import SimpleNamespace
    sort_key = item.entry_date or item.created_at
    return SimpleNamespace(
        id=item.id,
        entry_date=item.entry_date,
        sort_key=sort_key,
        direction=item.direction.value if hasattr(item.direction, "value") else item.direction,
        title=item.title,
        category=item.category,
        is_duplicate_flag=item.is_duplicate_flag,
        status=item.status.value if hasattr(item.status, "value") else item.status,
        source_mailbox=item.source_mailbox,
        source_type=(item.source_type.value if hasattr(item.source_type, "value") else item.source_type) if item.source_type else None,
        detail_url=f"/register/{item.id}",
    )


@router.get("/register", response_class=HTMLResponse)
def correspondence_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    query: str | None = None,
    direction: str | None = None,
    status_filter: str | None = None,
    category_id: int | None = None,
    source_mailbox: str | None = None,
):
    filters = CorrespondenceFilter(
        query=query or None,
        direction=Direction(direction) if direction else None,
        status=CorrespondenceStatus(status_filter) if status_filter else None,
        category_id=category_id,
        source_mailbox=source_mailbox or None,
    )
    correspondences = list_correspondence(db, filters)
    rows = [_wrap_correspondence_row(c) for c in correspondences]

    # Mail items are always incoming; include them unless the user filtered to outgoing.
    if direction != "outgoing":
        rows.extend(_build_mail_item_register_rows(
            db,
            query=query,
            status_filter=status_filter,
            category_id=category_id,
            source_mailbox=source_mailbox,
        ))

    from datetime import datetime as _datetime, timezone as _timezone
    def _sort_key(row):
        value = row.sort_key
        if value is None:
            return _datetime.min.replace(tzinfo=_timezone.utc)
        if hasattr(value, "tzinfo") and value.tzinfo is None:
            return value.replace(tzinfo=_timezone.utc)
        # plain date → midnight UTC
        if not hasattr(value, "tzinfo"):
            return _datetime.combine(value, _datetime.min.time(), tzinfo=_timezone.utc)
        return value
    rows.sort(key=_sort_key, reverse=True)

    categories = list_categories(db)
    return templates.TemplateResponse(
        request,
        "correspondence/list.html",
        template_context(request, db=db, current_user=current_user, items=rows, categories=categories, filters=filters),
    )


@router.get("/register/new", response_class=HTMLResponse)
def new_correspondence_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
):
    return templates.TemplateResponse(
        request,
        "correspondence/new.html",
        template_context(request, db=db, current_user=current_user, categories=list_categories(db), today=date.today()),
    )


@router.post("/register/new", dependencies=[Depends(verify_csrf)])
async def create_correspondence_html(
    request: Request,
    title: str = Form(...),
    entry_date: date = Form(...),
    category_id: int | None = Form(default=None),
    notes: str | None = Form(default=None),
    upload: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
):
    payload = CorrespondenceCreate(
        direction=Direction.OUTGOING,
        title=title,
        entry_date=entry_date,
        category_id=category_id,
        notes=notes,
        source_type=SourceType.MANUAL_UPLOAD if upload and upload.filename else SourceType.MANUAL_ENTRY,
    )
    stored = None
    if upload and upload.filename:
        stored_doc = await get_document_store().store_upload(upload)
        stored = stored_doc.__dict__
    create_manual_correspondence(db, current_user=current_user, payload=payload, stored_document=stored)
    return RedirectResponse(url="/register", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/correspondence/{correspondence_id}", response_class=HTMLResponse)
def correspondence_detail_redirect(correspondence_id: int):
    return RedirectResponse(url=f"/register/{correspondence_id}", status_code=status.HTTP_301_MOVED_PERMANENTLY)


@router.get("/register/{correspondence_id}", response_class=HTMLResponse)
def correspondence_detail(
    correspondence_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    partial: int = 0,
    return_to: str | None = None,
):
    item = db.scalar(
        select(Correspondence)
        .options(joinedload(Correspondence.category), joinedload(Correspondence.documents))
        .where(Correspondence.id == correspondence_id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    audit_entries = list_audit_entries(db, item.id)
    template_name = "correspondence/_detail_body.html" if partial else "correspondence/detail.html"
    return templates.TemplateResponse(
        request,
        template_name,
        template_context(
            request,
            db=db,
            current_user=current_user,
            item=item,
            categories=list_categories(db),
            audit_entries=audit_entries,
            editable=current_user.role in {Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR},
            return_to=_safe_return_to(return_to),
            compact=bool(partial),
        ),
    )


@router.post("/register/{correspondence_id}/edit", dependencies=[Depends(verify_csrf)])
def correspondence_edit_html(
    correspondence_id: int,
    request: Request,
    title: str = Form(...),
    entry_date: date = Form(...),
    status_value: CorrespondenceStatus = Form(...),
    category_id: int | None = Form(default=None),
    completion_note: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    placement_location: str | None = Form(default=None),
    handoff_target: str | None = Form(default=None),
    notification_done: str | None = Form(default=None),
    notification_channel: str | None = Form(default=None),
    notified_party: str | None = Form(default=None),
    processing_note: str | None = Form(default=None),
    return_to: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
):
    correspondence = db.scalar(
        select(Correspondence)
        .options(joinedload(Correspondence.category), joinedload(Correspondence.documents))
        .where(Correspondence.id == correspondence_id)
    )
    if correspondence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    payload = CorrespondenceUpdate(
        title=title,
        entry_date=entry_date,
        status=status_value,
        category_id=category_id,
        completion_note=completion_note,
        notes=notes,
        placement_location=placement_location or None,
        handoff_target=handoff_target or None,
        notification_done=notification_done == "on",
        notification_channel=notification_channel or None,
        notified_party=notified_party or None,
        processing_note=processing_note or None,
    )
    try:
        update_correspondence(db, correspondence=correspondence, current_user=current_user, payload=payload)
    except ValueError as exc:
        audit_entries = list_audit_entries(db, correspondence_id)
        return templates.TemplateResponse(
            request,
            "correspondence/detail.html",
            template_context(
                request,
                db=db,
                current_user=current_user,
                item=correspondence,
                categories=list_categories(db),
                audit_entries=audit_entries,
                editable=True,
                error=str(exc),
                return_to=_safe_return_to(return_to),
            ),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    redirect_url = _safe_return_to(return_to) or f"/register/{correspondence_id}"
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/register/{correspondence_id}/move-direction", dependencies=[Depends(verify_csrf)])
def correspondence_move_direction_html(
    correspondence_id: int,
    direction: Direction = Form(...),
    return_to: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
):
    correspondence = db.scalar(
        select(Correspondence)
        .options(joinedload(Correspondence.category), joinedload(Correspondence.documents))
        .where(Correspondence.id == correspondence_id)
    )
    if correspondence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    move_direction(
        db,
        correspondence=correspondence,
        current_user=current_user,
        payload=CorrespondenceDirectionUpdate(direction=direction),
    )
    if return_to:
        # If the caller came from the source channel, redirect to the destination channel
        # with the item pre-selected so the user follows the move.
        target_channel = (
            "/channels/paper-incoming" if direction == Direction.INCOMING else "/channels/paper-outgoing"
        )
        if return_to.startswith("/channels/paper-incoming") or return_to.startswith("/channels/paper-outgoing"):
            return RedirectResponse(
                url=f"{target_channel}?selected_id={correspondence_id}",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        safe = _safe_return_to(return_to)
        if safe:
            return RedirectResponse(url=safe, status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url=f"/register/{correspondence_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/categories", response_class=HTMLResponse)
def categories_page_redirect():
    return RedirectResponse(url="/admin/categories", status_code=status.HTTP_301_MOVED_PERMANENTLY)


@router.get("/admin/categories", response_class=HTMLResponse)
def categories_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(
        request,
        "categories/list.html",
        template_context(request, db=db, current_user=current_user, categories=list_categories(db)),
    )


@router.get("/categories/proposals", response_class=HTMLResponse)
def category_proposals_page_redirect():
    return RedirectResponse(url="/admin/suggestions", status_code=status.HTTP_301_MOVED_PERMANENTLY)


@router.get("/admin/suggestions", response_class=HTMLResponse)
def category_proposals_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    proposals = list(db.scalars(select(CategoryProposal).order_by(CategoryProposal.created_at.desc())))
    return templates.TemplateResponse(
        request,
        "categories/proposals.html",
        template_context(request, db=db, current_user=current_user, proposals=proposals, categories=list_categories(db)),
    )


@router.post("/admin/suggestions", dependencies=[Depends(verify_csrf)])
def category_proposal_html(
    request: Request,
    proposed_name: str = Form(...),
    proposal_reason: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
):
    create_proposal(
        db,
        current_user=current_user,
        payload=CategoryProposalCreate(proposed_name=proposed_name, proposal_reason=proposal_reason),
    )
    return RedirectResponse(url="/admin/suggestions", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/suggestions/{proposal_id}/approve", dependencies=[Depends(verify_csrf)])
def approve_proposal_html(
    proposal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN)),
):
    proposal = db.get(CategoryProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    review_proposal(db, proposal=proposal, current_user=current_user, approve=True)
    return RedirectResponse(url="/admin/suggestions", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/suggestions/{proposal_id}/reject", dependencies=[Depends(verify_csrf)])
def reject_proposal_html(
    proposal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN)),
):
    proposal = db.get(CategoryProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    review_proposal(db, proposal=proposal, current_user=current_user, approve=False)
    return RedirectResponse(url="/admin/suggestions", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/imports", response_class=HTMLResponse)
def imports_page_redirect():
    return RedirectResponse(url="/admin/import-monitor", status_code=status.HTTP_301_MOVED_PERMANENTLY)


@router.get("/admin/import-monitor", response_class=HTMLResponse)
def imports_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
):
    runs = list(db.scalars(select(ImportRun).order_by(ImportRun.started_at.desc()).limit(50)))
    messages = list(db.scalars(select(EmailMessage).order_by(EmailMessage.created_at.desc()).limit(100)))
    users = list(db.scalars(select(User).order_by(User.display_name)))
    return templates.TemplateResponse(
        request,
        "admin/imports.html",
        template_context(request, db=db, current_user=current_user, runs=runs, messages=messages, users=users),
    )


def _filter_users_for_admin_view(
    users: list[User],
    *,
    query: str,
    status_filter: str,
) -> list[User]:
    filtered = users
    if query:
        term = query.lower()
        filtered = [user for user in filtered if term in user.display_name.lower() or term in user.email.lower()]

    if status_filter == "active":
        filtered = [user for user in filtered if user.is_active]
    elif status_filter == "inactive":
        filtered = [user for user in filtered if not user.is_active]
    return filtered


@router.get("/admin/users", response_class=HTMLResponse)
def users_admin_page(
    request: Request,
    q: str | None = None,
    status_filter: str | None = None,
    created: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN)),
):
    users = list(db.scalars(select(User).order_by(User.display_name)))
    query = (q or "").strip()
    normalized_status = status_filter if status_filter in {"all", "active", "inactive"} else "all"
    visible_users = _filter_users_for_admin_view(users, query=query, status_filter=normalized_status)

    return templates.TemplateResponse(
        request,
        "admin/users.html",
        template_context(
            request,
            db=db,
            current_user=current_user,
            users=visible_users,
            filters={"q": query, "status": normalized_status},
            stats={
                "total": len(users),
                "active": sum(1 for user in users if user.is_active),
                "inactive": sum(1 for user in users if not user.is_active),
            },
            created=created == 1,
            create_error=None,
            create_form={"display_name": "", "email": "", "role": Role.VIEWER.value, "is_active": True},
        ),
    )


@router.post("/admin/users/new", dependencies=[Depends(verify_csrf)])
def users_admin_create(
    request: Request,
    email: str = Form(...),
    display_name: str = Form(...),
    role: Role = Form(default=Role.VIEWER),
    is_active: bool = Form(default=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN)),
):
    try:
        create_user(
            db,
            email=email,
            display_name=display_name,
            role=role,
            is_active=is_active,
            actor_user_id=current_user.id,
        )
    except ValueError as exc:
        users = list(db.scalars(select(User).order_by(User.display_name)))
        return templates.TemplateResponse(
            request,
            "admin/users.html",
            template_context(
                request,
                db=db,
                current_user=current_user,
                users=users,
                filters={"q": "", "status": "all"},
                stats={
                    "total": len(users),
                    "active": sum(1 for user in users if user.is_active),
                    "inactive": sum(1 for user in users if not user.is_active),
                },
                created=False,
                create_error=str(exc),
                create_form={
                    "display_name": display_name.strip(),
                    "email": email.strip(),
                    "role": role.value,
                    "is_active": is_active,
                },
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse(url="/admin/users?created=1", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/api/correspondence", response_model=list[CorrespondenceRead])
def api_list_correspondence(
    query: str | None = None,
    direction: Direction | None = None,
    status_filter: CorrespondenceStatus | None = None,
    category_id: int | None = None,
    source_mailbox: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return list_correspondence(
        db,
        CorrespondenceFilter(
            query=query,
            direction=direction,
            status=status_filter,
            category_id=category_id,
            source_mailbox=source_mailbox,
            date_from=date_from,
            date_to=date_to,
        ),
    )


@router.post("/api/correspondence", response_model=CorrespondenceRead, dependencies=[Depends(verify_csrf)])
async def api_create_correspondence(
    title: str = Form(...),
    entry_date: date = Form(...),
    category_id: int | None = Form(default=None),
    notes: str | None = Form(default=None),
    upload: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
):
    payload = CorrespondenceCreate(
        direction=Direction.OUTGOING,
        title=title,
        entry_date=entry_date,
        category_id=category_id,
        notes=notes,
        source_type=SourceType.MANUAL_UPLOAD if upload and upload.filename else SourceType.MANUAL_ENTRY,
    )
    stored = None
    if upload and upload.filename:
        stored = (await get_document_store().store_upload(upload)).__dict__
    return create_manual_correspondence(db, current_user=current_user, payload=payload, stored_document=stored)


@router.get("/api/correspondence/{correspondence_id}", response_model=CorrespondenceRead)
def api_get_correspondence(
    correspondence_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    item = db.scalar(
        select(Correspondence)
        .options(joinedload(Correspondence.category), joinedload(Correspondence.documents))
        .where(Correspondence.id == correspondence_id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return item


@router.patch("/api/correspondence/{correspondence_id}", response_model=CorrespondenceRead, dependencies=[Depends(verify_csrf)])
def api_update_correspondence(
    correspondence_id: int,
    payload: CorrespondenceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
):
    item = db.get(Correspondence, correspondence_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return update_correspondence(db, correspondence=item, current_user=current_user, payload=payload)


@router.post("/api/correspondence/{correspondence_id}/status", response_model=CorrespondenceRead, dependencies=[Depends(verify_csrf)])
def api_status_correspondence(
    correspondence_id: int,
    payload: CorrespondenceStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
):
    item = db.get(Correspondence, correspondence_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return transition_status(db, correspondence=item, current_user=current_user, payload=payload)


@router.post("/api/correspondence/{correspondence_id}/direction", response_model=CorrespondenceRead, dependencies=[Depends(verify_csrf)])
def api_move_correspondence_direction(
    correspondence_id: int,
    payload: CorrespondenceDirectionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
):
    item = db.get(Correspondence, correspondence_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return move_direction(db, correspondence=item, current_user=current_user, payload=payload)


@router.get("/api/correspondence/{correspondence_id}/document")
def api_get_document(
    correspondence_id: int,
    inline: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    document = db.scalar(select(Document).where(Document.correspondence_id == correspondence_id).order_by(Document.created_at.asc()))
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        download_url = get_document_store().generate_download_url(
            storage_bucket=document.storage_bucket,
            storage_key=document.storage_key,
            original_filename=document.original_filename,
            mime_type=document.mime_type,
            inline=inline,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    create_audit_entry(
        db,
        entity_type="document",
        entity_id=document.id,
        action="viewed",
        actor_user_id=current_user.id,
        before_json=None,
        after_json={
            "correspondence_id": correspondence_id,
            "filename": document.original_filename,
            "inline": inline,
        },
    )
    db.commit()
    return RedirectResponse(download_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/api/correspondence/{correspondence_id}/audit", response_model=list[AuditLogRead])
def api_get_audit(
    correspondence_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return list_audit_entries(db, correspondence_id)


@router.get("/api/categories", response_model=list[CategoryRead])
def api_categories(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return list_categories(db)


@router.post("/api/categories", response_model=CategoryRead, dependencies=[Depends(verify_csrf)])
def api_create_category(
    payload: CategoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
):
    try:
        return create_category(db, current_user=current_user, payload=payload)
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_409_CONFLICT if "existiert bereits" in detail else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.post("/api/category-proposals", response_model=CategoryProposalRead, dependencies=[Depends(verify_csrf)])
def api_create_proposal(
    payload: CategoryProposalCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
):
    return create_proposal(db, current_user=current_user, payload=payload)


@router.get("/api/category-proposals", response_model=list[CategoryProposalRead])
def api_list_proposals(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return list(db.scalars(select(CategoryProposal).order_by(CategoryProposal.created_at.desc())))


@router.post("/api/category-proposals/{proposal_id}/approve", response_model=CategoryProposalRead, dependencies=[Depends(verify_csrf)])
def api_approve_proposal(
    proposal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN)),
):
    proposal = db.get(CategoryProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return review_proposal(db, proposal=proposal, current_user=current_user, approve=True)


@router.post("/api/category-proposals/{proposal_id}/reject", response_model=CategoryProposalRead, dependencies=[Depends(verify_csrf)])
def api_reject_proposal(
    proposal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN)),
):
    proposal = db.get(CategoryProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return review_proposal(db, proposal=proposal, current_user=current_user, approve=False)


@router.get("/api/import-runs", response_model=list[ImportRunRead])
def api_import_runs(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
):
    return list(db.scalars(select(ImportRun).order_by(ImportRun.started_at.desc()).limit(100)))


@router.get("/api/email-messages", response_model=list[EmailMessageRead])
def api_email_messages(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
):
    return list(db.scalars(select(EmailMessage).order_by(EmailMessage.created_at.desc()).limit(200)))


@router.post("/api/import/run", dependencies=[Depends(verify_csrf)])
def api_import_run(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
):
    runs = run_import_cycle(db)
    create_audit_entry(
        db,
        entity_type="import",
        entity_id=None,
        action="manual_run_triggered",
        actor_user_id=current_user.id,
        before_json=None,
        after_json={"mailboxes": len(runs)},
    )
    db.commit()
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return RedirectResponse(url="/admin/import-monitor", status_code=status.HTTP_303_SEE_OTHER)
    return JSONResponse({"status": "completed", "mailboxes": len(runs)})


@router.post("/api/email-messages/{message_id}/retry", dependencies=[Depends(verify_csrf)])
def api_retry_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
):
    item = db.get(EmailMessage, message_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    before = {"processing_status": item.processing_status, "error_message": item.error_message}
    item.processing_status = "failed"
    item.error_message = "Marked for retry"
    item.processed_at = datetime.now(timezone.utc)
    create_audit_entry(
        db,
        entity_type="email_message",
        entity_id=item.id,
        action="retry_triggered",
        actor_user_id=current_user.id,
        before_json=before,
        after_json={"processing_status": item.processing_status},
    )
    db.commit()
    return JSONResponse({"status": "retry_marked"})


@router.get("/api/users", response_model=list[UserRead])
def api_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.SUPER_ADMIN)),
):
    return list(db.scalars(select(User).order_by(User.display_name)))


@router.post("/api/users", response_model=UserRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_csrf)])
def api_create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN)),
):
    try:
        return create_user(
            db,
            email=payload.email,
            display_name=payload.display_name,
            role=payload.role,
            is_active=payload.is_active,
            actor_user_id=current_user.id,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_409_CONFLICT if "already exists" in detail else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.patch("/api/users/{user_id}", response_model=UserRead, dependencies=[Depends(verify_csrf)])
def api_update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN)),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        return update_user(
            db,
            actor=current_user,
            target=target,
            display_name=payload.display_name,
            role=payload.role,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/api/users/{user_id}/role", response_model=UserRead, dependencies=[Depends(verify_csrf)])
def api_update_user_role(
    user_id: int,
    payload: UserRoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN)),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return update_user_role(db, actor=current_user, target=target, role=payload.role)


@router.patch("/api/users/{user_id}/active", response_model=UserRead, dependencies=[Depends(verify_csrf)])
def api_update_user_active(
    user_id: int,
    payload: UserActiveUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN)),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return update_user_active(db, actor=current_user, target=target, is_active=payload.is_active)


# ---------------------------------------------------------------------------
# Triage UI (general mailbox) — now at /channels/email-incoming
# ---------------------------------------------------------------------------


@router.get("/triage", response_class=HTMLResponse)
def triage_page_redirect(request: Request):
    qs = request.url.query
    url = "/channels/email-incoming" + (f"?{qs}" if qs else "")
    return RedirectResponse(url=url, status_code=status.HTTP_301_MOVED_PERMANENTLY)


@router.get("/triage/{mail_item_id}", response_class=HTMLResponse)
def triage_detail_redirect(mail_item_id: int):
    return RedirectResponse(url=f"/channels/email-incoming/{mail_item_id}", status_code=status.HTTP_301_MOVED_PERMANENTLY)


@router.get("/channels/email-incoming", response_class=HTMLResponse)
def email_incoming_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    assignment_scope: str | None = None,  # legacy
    status_scope: str | None = None,
    assigned_filter: str | None = None,
    q: str | None = None,
    category_id: int | None = None,
    assignee_id: int | None = None,
    selected_id: int | None = None,
    queue: str | None = None,
    status_filter: str | None = None,
):
    from datetime import date as _date

    open_statuses: list[MailItemStatus] = _EMAIL_OPEN_STATUSES
    closed_statuses: list[MailItemStatus] = _EMAIL_CLOSED_STATUSES
    all_statuses: list[MailItemStatus] = list(MailItemStatus)

    legacy_scope = (assignment_scope or queue or status_filter or "").strip().lower()

    def _normalize_status_scope(raw_value: str | None) -> str:
        token = (raw_value or "").strip().lower()
        if token in {"open", "all", "closed"}:
            return token
        if legacy_scope in {"all_open", "open"}:
            return "open"
        if legacy_scope in {"all"}:
            return "all"
        if legacy_scope in {"closed", "geschlossen"}:
            return "closed"
        if legacy_scope in {"neu", "in_bearbeitung", "wartet_aktion"}:
            return "open"
        return "open"

    def _normalize_assigned_filter(raw_value: str | None) -> tuple[str, int | None]:
        token = (raw_value or "").strip().lower()
        if token == "all":
            return "all", None
        if token == "unassigned":
            return "unassigned", None
        if token.startswith("user:"):
            suffix = token.split(":", 1)[1]
            if suffix.isdigit():
                user_id = int(suffix)
                if user_id > 0:
                    return f"user:{user_id}", user_id

        if legacy_scope in {"unassigned"}:
            return "unassigned", None
        if legacy_scope in {"mir"}:
            return f"user:{current_user.id}", current_user.id
        if legacy_scope in {"user"} and assignee_id is not None:
            return f"user:{assignee_id}", assignee_id
        return "all", None

    requested_status_scope = _normalize_status_scope(status_scope)
    requested_assigned_filter, requested_assignee_id = _normalize_assigned_filter(assigned_filter)

    status_scope_map: dict[str, list[MailItemStatus] | None] = {
        "open": open_statuses,
        "all": None,
        "closed": closed_statuses,
    }
    selected_statuses = status_scope_map[requested_status_scope]
    assigned_to_user_filter = requested_assignee_id if requested_assigned_filter.startswith("user:") else None
    assigned_is_null = requested_assigned_filter == "unassigned"

    items = list_mail_items_for_triage(
        db,
        status_filters=selected_statuses,
        assigned_to_user_id=assigned_to_user_filter,
        assigned_is_null=assigned_is_null,
        category_id=category_id,
        query=(q or "").strip() or None,
    )
    categories = list_categories(db)
    assignees = list(
        db.scalars(
            select(User)
            .where(User.is_active.is_(True))
            .order_by(User.display_name.asc())
        )
    )
    smtp_configured = bool(_get_effective_smtp(db)["host"])
    query_text = (q or "").strip()

    def _apply_common_filters(stmt):
        if category_id is not None:
            stmt = stmt.where(MailItem.category_id == category_id)
        if query_text:
            like = f"%{query_text}%"
            stmt = stmt.where(
                or_(
                    MailItem.subject.ilike(like),
                    MailItem.body_text.ilike(like),
                    MailItem.sender.ilike(like),
                )
            )
        return stmt

    def _count(
        *,
        statuses: list[MailItemStatus] | None,
        assigned_to_user_id: int | None = None,
        unassigned_only: bool = False,
    ) -> int:
        stmt = select(func.count(MailItem.id))
        if statuses is not None:
            stmt = stmt.where(MailItem.status.in_(statuses))
        if assigned_to_user_id is not None:
            stmt = stmt.where(MailItem.assigned_to_user_id == assigned_to_user_id)
        elif unassigned_only:
            stmt = stmt.where(MailItem.assigned_to_user_id.is_(None))
        stmt = _apply_common_filters(stmt)
        return int(db.scalar(stmt) or 0)

    def _count_with_assigned_filter(
        statuses: list[MailItemStatus] | None,
        filter_token: str,
        filter_user_id: int | None,
    ) -> int:
        if filter_token == "unassigned":
            return _count(statuses=statuses, unassigned_only=True)
        if filter_token.startswith("user:") and filter_user_id is not None:
            return _count(statuses=statuses, assigned_to_user_id=filter_user_id)
        return _count(statuses=statuses)

    status_counts = _email_status_counts(
        db,
        assigned_filter=requested_assigned_filter,
        assignee_id=requested_assignee_id,
        category_id=category_id,
        query_text=query_text,
    )

    assigned_counts: dict[str, int] = {
        "all": _count(statuses=selected_statuses),
        "unassigned": _count(statuses=selected_statuses, unassigned_only=True),
    }
    for assignee in assignees:
        assigned_counts[f"user:{assignee.id}"] = _count(statuses=selected_statuses, assigned_to_user_id=assignee.id)

    priority_meta_by_category_id: dict[int, dict[str, str]] = {}
    for category in categories:
        meta = _priority_from_category_name(category.name)
        if meta:
            priority_meta_by_category_id[category.id] = meta

    return templates.TemplateResponse(
        request,
        "channels/email_incoming.html",
        template_context(
            request,
            db=db,
            current_user=current_user,
            items=items,
            triage_mode=True,
            categories=categories,
            assignees=assignees,
            status_scope=requested_status_scope,
            status_counts=status_counts,
            assigned_filter=requested_assigned_filter,
            assigned_counts=assigned_counts,
            status_groups={
                "open": [status.value for status in open_statuses],
                "closed": [status.value for status in closed_statuses],
                "all": [status.value for status in all_statuses],
            },
            priority_meta_by_category_id=priority_meta_by_category_id,
            selected_id=selected_id,
            filters={
                "q": (q or "").strip(),
                "category_id": category_id,
                "status_scope": requested_status_scope,
                "assigned_filter": requested_assigned_filter,
                "assigned_user_id": requested_assignee_id,
            },
            today=_date.today(),
            smtp_configured=smtp_configured,
        ),
    )


@router.get("/channels/email-incoming/{mail_item_id}", response_class=HTMLResponse)
def email_incoming_detail(
    mail_item_id: int,
    request: Request,
    _: User = Depends(get_current_user),
):
    query = request.url.query
    suffix = f"&{query}" if query else ""
    return RedirectResponse(
        url=f"/channels/email-incoming?selected_id={mail_item_id}{suffix}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/channels/email-incoming/{mail_item_id}/update", dependencies=[Depends(verify_csrf)])
def email_incoming_update(
    mail_item_id: int,
    status_value: MailItemStatus = Form(...),
    category_id: int | None = Form(default=None),
    resolution_note: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
):
    if status_value in {MailItemStatus.CLOSED, MailItemStatus.SPAM}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Für den Abschluss bitte die Aktion 'Abschließen' bzw. 'Spam' verwenden.",
        )
    item = db.scalar(select(MailItem).where(MailItem.id == mail_item_id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    update_mail_item_from_patch(
        db,
        item=item,
        patch={
            "status": status_value.value,
            "category_id": category_id,
            "resolution_note": resolution_note,
        },
        actor_user_id=current_user.id,
        perform_writeback=perform_imap_writeback,
    )
    return RedirectResponse(url=f"/channels/email-incoming/{mail_item_id}", status_code=status.HTTP_303_SEE_OTHER)


# Keep legacy POST working (form in old triage detail template)
@router.post("/triage/{mail_item_id}/update", dependencies=[Depends(verify_csrf)])
def triage_update_legacy(
    mail_item_id: int,
    status_value: MailItemStatus = Form(...),
    category_id: int | None = Form(default=None),
    resolution_note: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
):
    if status_value in {MailItemStatus.CLOSED, MailItemStatus.SPAM}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Für den Abschluss bitte die Aktion 'Abschließen' bzw. 'Spam' verwenden.",
        )
    item = db.scalar(select(MailItem).where(MailItem.id == mail_item_id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    update_mail_item_from_patch(
        db,
        item=item,
        patch={
            "status": status_value.value,
            "category_id": category_id,
            "resolution_note": resolution_note,
        },
        actor_user_id=current_user.id,
        perform_writeback=perform_imap_writeback,
    )
    return RedirectResponse(url=f"/channels/email-incoming/{mail_item_id}", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------------
# Review queue (unified Zu prüfen)
# ---------------------------------------------------------------------------


@router.get("/review", response_class=HTMLResponse)
def review_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status_filter: str | None = None,
    channel: str | None = None,
):
    normalized_status = (status_filter or "neu").strip()
    if normalized_status not in {"neu", "in_bearbeitung", "wartet_aktion", "geschlossen"}:
        normalized_status = "neu"

    normalized_channel = (channel or "all").strip()
    if normalized_channel not in {"all", "email", "paper_incoming", "paper_outgoing"}:
        normalized_channel = "all"

    mail_status_map: dict[str, list[MailItemStatus]] = {
        "neu": [MailItemStatus.NEW],
        "in_bearbeitung": [MailItemStatus.IN_PROGRESS],
        "wartet_aktion": [MailItemStatus.WAITING],
        "geschlossen": [MailItemStatus.CLOSED, MailItemStatus.SPAM],
    }
    corr_status_map: dict[str, CorrespondenceStatus] = {
        "neu": CorrespondenceStatus.NEW,
        "in_bearbeitung": CorrespondenceStatus.IN_PROGRESS,
        "geschlossen": CorrespondenceStatus.DONE,
    }

    review_items: list[dict[str, Any]] = []

    if normalized_channel in {"all", "email"}:
        mail_stmt = (
            select(MailItem)
            .options(joinedload(MailItem.attachments))
            .order_by(MailItem.received_at.desc().nulls_last(), MailItem.created_at.desc())
        )
        mail_stmt = mail_stmt.where(MailItem.status.in_(mail_status_map[normalized_status]))
        mail_items = list(db.scalars(mail_stmt).unique())
        for item in mail_items:
            sort_at = item.received_at or item.created_at
            review_items.append({
                "channel": "email",
                "channel_label": "E-Mail",
                "channel_chip": "chip-eingang",
                "title": item.subject,
                "source": item.sender or "–",
                "received_at": sort_at,
                "status": item.status.value if hasattr(item.status, "value") else str(item.status),
                "href": f"/channels/email-incoming/{item.id}",
            })

    if normalized_status in corr_status_map and normalized_channel in {"all", "paper_incoming", "paper_outgoing"}:
        corr_status = corr_status_map[normalized_status]
        if normalized_channel in {"all", "paper_incoming"}:
            in_items = list_correspondence(
                db,
                CorrespondenceFilter(direction=Direction.INCOMING, status=corr_status),
            )
            for item in in_items:
                review_items.append({
                    "channel": "paper_incoming",
                    "channel_label": "Papier-Eingang",
                    "channel_chip": "chip-eingang",
                    "title": item.title,
                    "source": item.source_mailbox or item.source_type or "–",
                    "received_at": item.created_at,
                    "entry_date": item.entry_date,
                    "status": item.status.value if hasattr(item.status, "value") else str(item.status),
                    "href": f"/register/{item.id}",
                })
        if normalized_channel in {"all", "paper_outgoing"}:
            out_items = list_correspondence(
                db,
                CorrespondenceFilter(direction=Direction.OUTGOING, status=corr_status),
            )
            for item in out_items:
                review_items.append({
                    "channel": "paper_outgoing",
                    "channel_label": "Papier-Ausgang",
                    "channel_chip": "chip-ausgang",
                    "title": item.title,
                    "source": item.source_mailbox or item.source_type or "–",
                    "received_at": item.created_at,
                    "entry_date": item.entry_date,
                    "status": item.status.value if hasattr(item.status, "value") else str(item.status),
                    "href": f"/register/{item.id}",
                })

    def _sort_key(row: dict[str, Any]) -> float:
        value = row.get("received_at")
        if isinstance(value, datetime):
            return value.timestamp()
        return 0.0

    review_items.sort(key=_sort_key, reverse=True)
    return templates.TemplateResponse(
        request,
        "triage/review.html",
        template_context(
            request,
            db=db,
            current_user=current_user,
            items=review_items,
            status_filter=normalized_status,
            channel_filter=normalized_channel,
        ),
    )


# ---------------------------------------------------------------------------
# Paper channel pages (stubs — data model TBD)
# ---------------------------------------------------------------------------


def _paper_channel_context(
    request: Request,
    db: Session,
    current_user: User,
    direction: Direction,
    status_filter: str | None,
    selected_id: int | None,
) -> dict[str, Any]:
    status_enum = CorrespondenceStatus(status_filter) if status_filter else None
    items = list_correspondence(
        db, CorrespondenceFilter(direction=direction, status=status_enum)
    )
    selected_item = None
    audit_entries: list[Any] = []
    categories: list[Any] = []
    if selected_id is not None:
        selected_item = db.scalar(
            select(Correspondence)
            .options(joinedload(Correspondence.category), joinedload(Correspondence.documents))
            .where(Correspondence.id == selected_id)
        )
        if selected_item is not None:
            audit_entries = list_audit_entries(db, selected_item.id)
            categories = list_categories(db)
    base_path = (
        "/channels/paper-incoming" if direction == Direction.INCOMING else "/channels/paper-outgoing"
    )
    query_parts = []
    if status_filter:
        query_parts.append(f"status_filter={status_filter}")
    if selected_id is not None and selected_item is not None:
        query_parts.append(f"selected_id={selected_id}")
    return_to = base_path + (("?" + "&".join(query_parts)) if query_parts else "")
    return template_context(
        request,
        db=db,
        current_user=current_user,
        items=items,
        status_filter=status_filter or "",
        selected_item=selected_item,
        categories=categories,
        audit_entries=audit_entries,
        editable=current_user.role in {Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR},
        return_to=return_to,
    )


@router.get("/channels/paper-incoming", response_class=HTMLResponse)
def paper_incoming_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status_filter: str | None = None,
    selected_id: int | None = None,
):
    return templates.TemplateResponse(
        request,
        "channels/paper_incoming.html",
        _paper_channel_context(
            request, db, current_user, Direction.INCOMING, status_filter, selected_id
        ),
    )


@router.get("/channels/paper-outgoing", response_class=HTMLResponse)
def paper_outgoing_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status_filter: str | None = None,
    selected_id: int | None = None,
):
    return templates.TemplateResponse(
        request,
        "channels/paper_outgoing.html",
        _paper_channel_context(
            request, db, current_user, Direction.OUTGOING, status_filter, selected_id
        ),
    )


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------


@router.get("/duplicates", response_class=HTMLResponse)
def duplicates_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = list_correspondence(db, CorrespondenceFilter())
    duplicate_items = [i for i in items if i.is_duplicate_flag]
    return templates.TemplateResponse(
        request,
        "duplicates/list.html",
        template_context(request, db=db, current_user=current_user, items=duplicate_items),
    )


# ---------------------------------------------------------------------------
# Workflow configuration stubs
# ---------------------------------------------------------------------------


@router.get("/workflows/routes", response_class=HTMLResponse)
def workflows_routes_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
):
    routes = list(db.scalars(select(ForwardingRoute).order_by(ForwardingRoute.sort_order, ForwardingRoute.id)))
    return templates.TemplateResponse(
        request,
        "workflows/routes.html",
        template_context(request, db=db, current_user=current_user, routes=routes),
    )


@router.get("/workflows/templates", response_class=HTMLResponse)
def workflows_templates_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
):
    return templates.TemplateResponse(
        request,
        "workflows/templates.html",
        template_context(request, db=db, current_user=current_user),
    )


@router.get("/workflows/rules", response_class=HTMLResponse)
def workflows_rules_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
):
    return templates.TemplateResponse(
        request,
        "workflows/rules.html",
        template_context(request, db=db, current_user=current_user),
    )


# ---------------------------------------------------------------------------
# Mail items (general triage mailbox)
# ---------------------------------------------------------------------------


@router.get("/api/mail-items", response_model=list[MailItemRead])
def api_list_mail_items(
    mailbox_id: int | None = None,
    status_filter: MailItemStatus | None = None,
    status_filters: str | None = None,
    category_id: int | None = None,
    assigned_to_user_id: int | None = None,
    query: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    parsed_status_filters: list[MailItemStatus] = []
    if status_filters:
        for raw in status_filters.split(","):
            token = raw.strip()
            if not token:
                continue
            try:
                parsed_status_filters.append(MailItemStatus(token))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Invalid mail item status: {token}") from exc
    if status_filter is not None:
        parsed_status_filters.append(status_filter)

    return list_mail_items_for_triage(
        db,
        mailbox_id=mailbox_id,
        status_filters=parsed_status_filters or None,
        category_id=category_id,
        assigned_to_user_id=assigned_to_user_id,
        query=query,
    )


@router.get("/api/mail-items/{mail_item_id}", response_model=MailItemRead)
def api_get_mail_item(
    mail_item_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    item = db.scalar(
        select(MailItem).options(joinedload(MailItem.attachments)).where(MailItem.id == mail_item_id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return item


@router.get("/api/mail-items/{mail_item_id}/timeline", response_model=list[MailItemTimelineEventRead])
def api_get_mail_item_timeline(
    mail_item_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if db.get(MailItem, mail_item_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    timeline = get_mail_item_timeline(db, mail_item_id=mail_item_id)
    actor_ids = sorted({entry.actor_user_id for entry in timeline if entry.actor_user_id is not None})
    actor_map = {
        user.id: user.display_name
        for user in db.scalars(select(User).where(User.id.in_(actor_ids)))
    } if actor_ids else {}
    return [
        MailItemTimelineEventRead(
            id=entry.id,
            action=entry.action,
            actor_user_id=entry.actor_user_id,
            actor_display_name=actor_map.get(entry.actor_user_id),
            before_json=entry.before_json,
            after_json=entry.after_json,
            created_at=entry.created_at,
        )
        for entry in timeline
    ]


def _initials_from_display_name(name: str | None) -> str:
    if not name:
        return ""
    parts = [p for p in name.strip().split() if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _serialize_mail_item_note(note: "MailItemNote", author_map: dict[int, User]) -> MailItemNoteRead:
    author = author_map.get(note.author_user_id) if note.author_user_id is not None else None
    return MailItemNoteRead(
        id=note.id,
        mail_item_id=note.mail_item_id,
        author_user_id=note.author_user_id,
        author_display_name=author.display_name if author else None,
        author_initials=_initials_from_display_name(author.display_name) if author else None,
        body=note.body,
        created_at=note.created_at,
    )


@router.get("/api/mail-items/{mail_item_id}/notes", response_model=list[MailItemNoteRead])
def api_list_mail_item_notes(
    mail_item_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if db.get(MailItem, mail_item_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    notes = list_mail_item_notes(db, mail_item_id=mail_item_id)
    author_ids = sorted({note.author_user_id for note in notes if note.author_user_id is not None})
    author_map = {
        user.id: user
        for user in db.scalars(select(User).where(User.id.in_(author_ids)))
    } if author_ids else {}
    return [_serialize_mail_item_note(note, author_map) for note in notes]


@router.post(
    "/api/mail-items/{mail_item_id}/notes",
    response_model=MailItemNoteRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_csrf)],
)
def api_create_mail_item_note(
    mail_item_id: int,
    payload: MailItemNoteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
):
    item = db.get(MailItem, mail_item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        note = add_mail_item_note(
            db,
            mail_item=item,
            author_user_id=current_user.id,
            body=payload.body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    db.refresh(note)
    author_map = {current_user.id: current_user}
    return _serialize_mail_item_note(note, author_map)


@router.patch("/api/mail-items/{mail_item_id}", response_model=MailItemRead, dependencies=[Depends(verify_csrf)])
def api_update_mail_item(
    mail_item_id: int,
    payload: MailItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
):
    if payload.status in {MailItemStatus.CLOSED, MailItemStatus.SPAM}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Direktes Setzen auf 'Abgeschlossen' oder 'Spam' ist hier nicht erlaubt.",
        )
    item = db.scalar(
        select(MailItem).options(joinedload(MailItem.attachments)).where(MailItem.id == mail_item_id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return update_mail_item_from_patch(
        db,
        item=item,
        patch=payload.model_dump(exclude_unset=True),
        actor_user_id=current_user.id,
        perform_writeback=perform_imap_writeback,
    )


@router.post("/api/mail-items/{mail_item_id}/assign-category", response_model=MailItemRead, dependencies=[Depends(verify_csrf)])
def api_assign_category(
    mail_item_id: int,
    payload: MailItemAssignCategory,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
):
    item = db.scalar(
        select(MailItem).options(joinedload(MailItem.attachments)).where(MailItem.id == mail_item_id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return update_mail_item_from_patch(
        db,
        item=item,
        patch={"category_id": payload.category_id},
        actor_user_id=current_user.id,
        perform_writeback=perform_imap_writeback,
    )


@router.post("/api/mail-items/{mail_item_id}/close", response_model=MailItemRead, dependencies=[Depends(verify_csrf)])
def api_close_mail_item(
    mail_item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
):
    item = db.scalar(
        select(MailItem).options(joinedload(MailItem.attachments)).where(MailItem.id == mail_item_id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return close_mail_item(
        db,
        item=item,
        actor_user_id=current_user.id,
        perform_writeback=perform_imap_writeback,
    )


@router.post("/api/mail-items/{mail_item_id}/spam", response_model=MailItemRead, dependencies=[Depends(verify_csrf)])
def api_mark_mail_item_spam(
    mail_item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
):
    item = db.scalar(
        select(MailItem).options(joinedload(MailItem.attachments)).where(MailItem.id == mail_item_id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return mark_mail_item_spam(
        db,
        item=item,
        actor_user_id=current_user.id,
        perform_writeback=perform_imap_writeback,
    )


@router.get("/api/triage/assignees", response_model=list[TriageAssigneeRead])
def api_list_triage_assignees(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return list(
        db.scalars(
            select(User)
            .where(User.is_active.is_(True))
            .order_by(User.display_name.asc())
        )
    )


@router.get("/api/email-cases/{case_id}", response_model=EmailCaseDetailRead)
def api_get_email_case_detail(
    case_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    case = db.get(EmailCase, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    messages = list(
        db.scalars(
            select(MailItem)
            .options(joinedload(MailItem.attachments))
            .where(MailItem.case_id == case_id)
            .order_by(MailItem.received_at.asc().nulls_last(), MailItem.id.asc())
        ).unique()
    )
    events = list(
        db.scalars(
            select(EmailCaseEvent)
            .where(EmailCaseEvent.case_id == case_id)
            .order_by(EmailCaseEvent.created_at.asc(), EmailCaseEvent.id.asc())
        )
    )
    return {"case": case, "messages": messages, "events": events}


# ---------------------------------------------------------------------------
# Forwarding routes API
# ---------------------------------------------------------------------------


@router.get("/api/forwarding-routes", response_model=list[ForwardingRouteRead])
def api_list_forwarding_routes(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Return active forwarding routes with their templates for the drawer UI."""
    import logging
    routes = list(
        db.scalars(
            select(ForwardingRoute)
            .options(joinedload(ForwardingRoute.templates))
            .where(ForwardingRoute.is_active == True)  # noqa: E712
            .order_by(ForwardingRoute.sort_order, ForwardingRoute.id)
        ).unique()
    )
    return routes


@router.post("/api/mail-items/{mail_item_id}/forward", response_model=MailItemRead, dependencies=[Depends(verify_csrf)])
def api_forward_mail_item(
    mail_item_id: int,
    payload: ForwardActionPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
):
    import json
    import logging

    logger = logging.getLogger(__name__)

    item = db.scalar(
        select(MailItem).options(joinedload(MailItem.attachments)).where(MailItem.id == mail_item_id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # Build the target record and resolve destination email
    target: dict = {"target_type": payload.target_type}
    to_email: str | None = None

    if payload.target_type == "route" and payload.route_id is not None:
        route = db.get(ForwardingRoute, payload.route_id)
        if route is None:
            raise HTTPException(status_code=404, detail="Weiterleitungsziel nicht gefunden.")
        target["route_id"] = route.id
        target["route_name"] = route.name
        to_email = route.target_email
    elif payload.target_type == "user" and payload.user_id is not None:
        fwd_user = db.get(User, payload.user_id)
        if fwd_user is None:
            raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")
        target["user_id"] = fwd_user.id
        target["user_name"] = fwd_user.display_name
        target["user_email"] = fwd_user.email
        to_email = fwd_user.email
    elif payload.target_type == "external" and payload.external_email:
        target["external_email"] = payload.external_email
        to_email = payload.external_email
    elif payload.target_type == "reply":
        _, sender_email = parseaddr(item.sender or "")
        if not sender_email:
            raise HTTPException(status_code=400, detail="Antwort nicht möglich: Absender-E-Mail fehlt.")
        target["reply_to"] = sender_email
        to_email = sender_email
    else:
        raise HTTPException(status_code=400, detail="Ungültiges Weiterleitungsziel.")

    custom_subject = (payload.message_subject or "").strip()
    custom_body = (payload.message_body or "").strip()
    has_custom_message = bool(custom_subject or custom_body)
    is_reply = payload.target_type == "reply"
    after_status = MailItemStatus(payload.after_status)
    if after_status in {MailItemStatus.CLOSED, MailItemStatus.SPAM}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Weiterleiten/Antworten darf nicht automatisch schließen oder als Spam markieren.",
        )

    item = record_forward_decision(
        db,
        item=item,
        target_json=target,
        after_status=after_status,
        note=payload.note,
        actor_user_id=current_user.id,
        action_type=MailItemActionType.REPLY if is_reply else MailItemActionType.FORWARD,
        reply_subject=custom_subject if custom_subject else None,
        reply_body=custom_body if custom_body else None,
        event_action="replied" if is_reply else "forwarded",
        perform_writeback=perform_imap_writeback,
    )

    # Send email via SMTP (best-effort) whenever we have a destination and SMTP is configured
    smtp = _get_effective_smtp(db)
    if to_email and smtp["host"]:
        # Use received_at if available, fall back to when the item was imported
        effective_date = item.received_at or item.created_at
        if has_custom_message:
            rendered_subject = custom_subject or ("Antwort: " + (item.subject or "") if is_reply else "Weiterleitung")
            rendered_body = custom_body
        else:
            tpl = db.get(ForwardingTemplate, payload.template_id) if payload.template_id is not None else None
            if tpl is not None:
                rendered_subject = render_fwd_template(
                    tpl.subject_template,
                    subject=item.subject,
                    sender=item.sender,
                    received_at=effective_date,
                    body_text=item.body_text,
                    body_html=item.body_html,
                )
                rendered_body = render_fwd_template(
                    tpl.body_template,
                    subject=item.subject,
                    sender=item.sender,
                    received_at=effective_date,
                    body_text=item.body_text,
                    body_html=item.body_html,
                )
            elif is_reply:
                rendered_subject = f"Antwort: {item.subject}" if item.subject else "Antwort"
                rendered_body = ""
            else:
                # No template selected — use built-in forward format with full original content
                rendered_subject, rendered_body = render_default_forward(
                    subject=item.subject,
                    sender=item.sender,
                    received_at=effective_date,
                    body_text=item.body_text,
                    body_html=item.body_html,
                )
        try:
            msg_bytes = send_forward_email(
                to=to_email,
                subject=rendered_subject,
                body=rendered_body,
                smtp_host=smtp["host"],
                smtp_port=smtp["port"],
                smtp_username=smtp["username"],
                smtp_password=smtp["password"],
                smtp_from_address=smtp["from_address"],
                smtp_use_tls=smtp["use_tls"],
            )
            target["email_sent"] = True
            target["email_to"] = to_email
            target["message_subject"] = rendered_subject
            target["message_body"] = rendered_body
            item.forward_targets_json = json.dumps(target, ensure_ascii=False)
            db.commit()
        except Exception as exc:
            logger.warning("Forward email send failed for mail_item %s: %s", mail_item_id, exc)
            msg_bytes = None

        # IMAP APPEND: save the sent message into the SMTP sender's Sent folder (best-effort)
        if msg_bytes is not None and smtp["host"] and smtp["username"]:
            try:
                IMAPPollService().append_to_sent(
                    host=smtp["host"],
                    username=smtp["username"],
                    password=smtp["password"] or "",
                    msg_bytes=msg_bytes,
                    sent_folder="Sent",
                )
                logger.info("Appended sent message to IMAP Sent folder (%s) for mail_item %s", smtp["username"], mail_item_id)
            except Exception as exc:
                logger.warning("IMAP append to Sent folder failed for mail_item %s: %s", mail_item_id, exc)

    return item


# Admin CRUD for forwarding routes (admin+ only)

@router.get("/admin/api/forwarding-routes", response_model=list[ForwardingRouteRead])
def admin_list_forwarding_routes(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
):
    return list(
        db.scalars(
            select(ForwardingRoute)
            .options(joinedload(ForwardingRoute.templates))
            .order_by(ForwardingRoute.sort_order, ForwardingRoute.id)
        )
    )


def _serialize_forwarding_route(route: ForwardingRoute) -> dict:
    return {
        "name": route.name,
        "target_email": route.target_email,
        "is_active": route.is_active,
        "sort_order": route.sort_order,
    }


@router.post("/admin/api/forwarding-routes", response_model=ForwardingRouteRead, dependencies=[Depends(verify_csrf)])
def admin_create_forwarding_route(
    payload: ForwardingRouteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
):
    route = ForwardingRoute(**payload.model_dump())
    db.add(route)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ein Weiterleitungsziel mit diesem Namen existiert bereits.")
    create_audit_entry(
        db,
        entity_type="forwarding_route",
        entity_id=route.id,
        action="created",
        actor_user_id=current_user.id,
        before_json=None,
        after_json=_serialize_forwarding_route(route),
    )
    db.commit()
    db.refresh(route)
    return route


@router.patch("/admin/api/forwarding-routes/{route_id}", response_model=ForwardingRouteRead, dependencies=[Depends(verify_csrf)])
def admin_update_forwarding_route(
    route_id: int,
    payload: ForwardingRouteUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
):
    route = db.get(ForwardingRoute, route_id)
    if route is None:
        raise HTTPException(status_code=404)
    before = _serialize_forwarding_route(route)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(route, field, value)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ein Weiterleitungsziel mit diesem Namen existiert bereits.")
    create_audit_entry(
        db,
        entity_type="forwarding_route",
        entity_id=route.id,
        action="updated",
        actor_user_id=current_user.id,
        before_json=before,
        after_json=_serialize_forwarding_route(route),
    )
    db.commit()
    db.refresh(route)
    return route


@router.delete("/admin/api/forwarding-routes/{route_id}", dependencies=[Depends(verify_csrf)])
def admin_delete_forwarding_route(
    route_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
):
    route = db.get(ForwardingRoute, route_id)
    if route is None:
        raise HTTPException(status_code=404)
    before = _serialize_forwarding_route(route)
    db.query(ForwardingTemplate).filter(ForwardingTemplate.forwarding_route_id == route_id).delete()
    db.delete(route)
    create_audit_entry(
        db,
        entity_type="forwarding_route",
        entity_id=route_id,
        action="deleted",
        actor_user_id=current_user.id,
        before_json=before,
        after_json=None,
    )
    db.commit()
    return {"ok": True}


# Template CRUD (admin+ only)

def _serialize_forwarding_template(tpl: ForwardingTemplate) -> dict:
    return {
        "name": tpl.name,
        "forwarding_route_id": tpl.forwarding_route_id,
        "subject_template": tpl.subject_template,
        "body_template": tpl.body_template,
        "is_default": tpl.is_default,
        "is_active": tpl.is_active,
    }


@router.post(
    "/admin/api/forwarding-routes/{route_id}/templates",
    response_model=ForwardingTemplateRead,
    dependencies=[Depends(verify_csrf)],
)
def admin_create_forwarding_template(
    route_id: int,
    payload: ForwardingTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
):
    route = db.get(ForwardingRoute, route_id)
    if route is None:
        raise HTTPException(status_code=404)
    # If this template is set as default, unset others for this route
    if payload.is_default:
        db.execute(
            select(ForwardingTemplate)
            .where(ForwardingTemplate.forwarding_route_id == route_id)
        )
        for tpl in route.templates:
            tpl.is_default = False
    template = ForwardingTemplate(forwarding_route_id=route_id, **payload.model_dump())
    db.add(template)
    db.flush()
    create_audit_entry(
        db,
        entity_type="forwarding_template",
        entity_id=template.id,
        action="created",
        actor_user_id=current_user.id,
        before_json=None,
        after_json=_serialize_forwarding_template(template),
    )
    db.commit()
    db.refresh(template)
    return template


@router.patch(
    "/admin/api/forwarding-templates/{template_id}",
    response_model=ForwardingTemplateRead,
    dependencies=[Depends(verify_csrf)],
)
def admin_update_forwarding_template(
    template_id: int,
    payload: ForwardingTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
):
    tpl = db.get(ForwardingTemplate, template_id)
    if tpl is None:
        raise HTTPException(status_code=404)
    before = _serialize_forwarding_template(tpl)
    # If setting as default, unset others for the same route
    if payload.is_default:
        for other in db.scalars(
            select(ForwardingTemplate).where(
                ForwardingTemplate.forwarding_route_id == tpl.forwarding_route_id,
                ForwardingTemplate.id != template_id,
            )
        ):
            other.is_default = False
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(tpl, field, value)
    create_audit_entry(
        db,
        entity_type="forwarding_template",
        entity_id=tpl.id,
        action="updated",
        actor_user_id=current_user.id,
        before_json=before,
        after_json=_serialize_forwarding_template(tpl),
    )
    db.commit()
    db.refresh(tpl)
    return tpl


@router.delete("/admin/api/forwarding-templates/{template_id}", dependencies=[Depends(verify_csrf)])
def admin_delete_forwarding_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
):
    tpl = db.get(ForwardingTemplate, template_id)
    if tpl is None:
        raise HTTPException(status_code=404)
    before = _serialize_forwarding_template(tpl)
    tpl.is_active = False
    create_audit_entry(
        db,
        entity_type="forwarding_template",
        entity_id=tpl.id,
        action="deleted",
        actor_user_id=current_user.id,
        before_json=before,
        after_json=_serialize_forwarding_template(tpl),
    )
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Mailbox administration (super_admin only)
# ---------------------------------------------------------------------------


@router.get("/admin/mailboxes", response_class=HTMLResponse)
def admin_mailboxes_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN)),
    error: str | None = None,
    smtp_saved: str | None = None,
):
    mailboxes = list(db.scalars(select(Mailbox).order_by(Mailbox.id)))
    smtp_cfg = db.get(SmtpConfig, 1)
    # Pre-fill from env if no DB row yet
    if smtp_cfg is None:
        s = get_settings()
        smtp_cfg = SmtpConfig(
            id=1,
            smtp_host=s.smtp_host or "",
            smtp_port=s.smtp_port,
            smtp_username=s.smtp_username or "",
            smtp_password="",  # never pre-fill password from env
            smtp_from_address=s.smtp_from_address or "",
            smtp_use_tls=s.smtp_use_tls,
        )
    return templates.TemplateResponse(
        request,
        "admin/mailboxes.html",
        template_context(
            request,
            db=db,
            current_user=current_user,
            mailboxes=mailboxes,
            directions=list(Direction),
            processing_modes=list(MailboxProcessingMode),
            error=error,
            smtp_cfg=smtp_cfg,
            smtp_saved=smtp_saved == "1",
        ),
    )


def _serialize_mailbox(mb: Mailbox) -> dict:
    return {
        "name": mb.name,
        "direction": mb.direction.value if hasattr(mb.direction, "value") else mb.direction,
        "processing_mode": mb.processing_mode.value if hasattr(mb.processing_mode, "value") else mb.processing_mode,
        "imap_folder": mb.imap_folder,
        "processed_folder": mb.processed_folder,
        "is_active": mb.is_active,
        "imap_host": mb.imap_host,
        "imap_port": mb.imap_port,
        "imap_use_ssl": mb.imap_use_ssl,
        "imap_username": mb.imap_username,
        "fetch_since": mb.fetch_since.isoformat() if mb.fetch_since else None,
    }


@router.post("/admin/mailboxes/new", dependencies=[Depends(verify_csrf)])
def admin_create_mailbox(
    request: Request,
    name: str = Form(...),
    direction: Direction = Form(...),
    processing_mode: MailboxProcessingMode = Form(...),
    imap_folder: str = Form(default="INBOX"),
    processed_folder: str = Form(default="Processed"),
    is_active: bool = Form(default=True),
    imap_host: str = Form(...),
    imap_port: int = Form(default=993),
    imap_use_ssl: bool = Form(default=True),
    imap_username: str = Form(...),
    imap_password: str = Form(...),
    fetch_since: date | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN)),
):
    mailbox = Mailbox(
        name=name.strip(),
        direction=direction,
        processing_mode=processing_mode,
        imap_folder=imap_folder.strip(),
        processed_folder=processed_folder.strip(),
        is_active=is_active,
        imap_host=imap_host.strip(),
        imap_port=imap_port,
        imap_use_ssl=imap_use_ssl,
        imap_username=imap_username.strip(),
        imap_password=imap_password,
        fetch_since=fetch_since,
    )
    db.add(mailbox)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            url="/admin/mailboxes?error=name_exists",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    create_audit_entry(
        db,
        entity_type="mailbox",
        entity_id=mailbox.id,
        action="created",
        actor_user_id=current_user.id,
        before_json=None,
        after_json=_serialize_mailbox(mailbox),
    )
    db.commit()
    return RedirectResponse(url="/admin/mailboxes", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/mailboxes/{mailbox_id}/edit", dependencies=[Depends(verify_csrf)])
def admin_edit_mailbox(
    mailbox_id: int,
    direction: Direction = Form(...),
    processing_mode: MailboxProcessingMode = Form(...),
    imap_folder: str = Form(...),
    processed_folder: str = Form(...),
    is_active: bool = Form(default=False),
    imap_host: str = Form(...),
    imap_port: int = Form(default=993),
    imap_use_ssl: bool = Form(default=False),
    imap_username: str = Form(...),
    imap_password: str = Form(default=""),
    fetch_since: date | None = Form(default=None),
    name: str = Form(default=""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN)),
):
    mailbox = db.get(Mailbox, mailbox_id)
    if mailbox is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    before = _serialize_mailbox(mailbox)
    if name.strip():
        mailbox.name = name.strip()
    mailbox.direction = direction
    mailbox.processing_mode = processing_mode
    mailbox.imap_folder = imap_folder.strip()
    mailbox.processed_folder = processed_folder.strip()
    mailbox.is_active = is_active
    mailbox.imap_host = imap_host.strip()
    mailbox.imap_port = imap_port
    mailbox.imap_use_ssl = imap_use_ssl
    mailbox.imap_username = imap_username.strip()
    if imap_password.strip():
        mailbox.imap_password = imap_password
    mailbox.fetch_since = fetch_since
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            url="/admin/mailboxes?error=name_exists",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    create_audit_entry(
        db,
        entity_type="mailbox",
        entity_id=mailbox.id,
        action="updated",
        actor_user_id=current_user.id,
        before_json=before,
        after_json=_serialize_mailbox(mailbox),
    )
    db.commit()
    return RedirectResponse(url="/admin/mailboxes", status_code=status.HTTP_303_SEE_OTHER)


def _serialize_smtp(cfg: SmtpConfig) -> dict:
    return {
        "smtp_host": cfg.smtp_host,
        "smtp_port": cfg.smtp_port,
        "smtp_username": cfg.smtp_username,
        "smtp_from_address": cfg.smtp_from_address,
        "smtp_use_tls": cfg.smtp_use_tls,
    }


@router.post("/admin/smtp-config", dependencies=[Depends(verify_csrf)])
def admin_save_smtp_config(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN)),
    smtp_host: str = Form(default=""),
    smtp_port: int = Form(default=587),
    smtp_username: str = Form(default=""),
    smtp_password: str = Form(default=""),
    smtp_from_address: str = Form(default=""),
    smtp_use_tls: str = Form(default=""),
):
    cfg = db.get(SmtpConfig, 1)
    is_new = cfg is None
    if cfg is None:
        cfg = SmtpConfig(id=1)
        db.add(cfg)
        before = None
    else:
        before = _serialize_smtp(cfg)
    cfg.smtp_host = smtp_host.strip() or None
    cfg.smtp_port = smtp_port
    cfg.smtp_username = smtp_username.strip() or None
    password_changed = bool(smtp_password.strip())
    if password_changed:
        cfg.smtp_password = smtp_password.strip()
    cfg.smtp_from_address = smtp_from_address.strip() or None
    cfg.smtp_use_tls = smtp_use_tls == "true"
    after = _serialize_smtp(cfg)
    after["password_changed"] = password_changed
    create_audit_entry(
        db,
        entity_type="smtp_config",
        entity_id=1,
        action="created" if is_new else "updated",
        actor_user_id=current_user.id,
        before_json=before,
        after_json=after,
    )
    db.commit()
    return RedirectResponse(url="/admin/mailboxes?smtp_saved=1", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/api/mail-items/{mail_item_id}/attachment/{attachment_id}")
def api_download_mail_item_attachment(
    mail_item_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    attachment = db.scalar(
        select(MailItemAttachment).where(
            MailItemAttachment.id == attachment_id,
            MailItemAttachment.mail_item_id == mail_item_id,
        )
    )
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        download_url = get_document_store().generate_download_url(
            storage_bucket=attachment.storage_bucket,
            storage_key=attachment.storage_key,
            original_filename=attachment.original_filename,
            mime_type=attachment.mime_type,
            inline=False,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    create_audit_entry(
        db,
        entity_type="mail_item_attachment",
        entity_id=attachment.id,
        action="viewed",
        actor_user_id=current_user.id,
        before_json=None,
        after_json={
            "mail_item_id": mail_item_id,
            "filename": attachment.original_filename,
        },
    )
    db.commit()
    return RedirectResponse(download_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


# ---------------------------------------------------------------------------
# Audit log viewer (admin+ only)
# ---------------------------------------------------------------------------


def _parse_audit_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _audit_filter_conditions(
    *,
    action: str | None,
    actor_user_id: int | None,
    entity_type: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> list:
    conditions: list = []
    if action:
        conditions.append(AuditLog.action == action)
    if actor_user_id is not None:
        conditions.append(AuditLog.actor_user_id == actor_user_id)
    if entity_type:
        conditions.append(AuditLog.entity_type == entity_type)
    if date_from is not None:
        conditions.append(AuditLog.created_at >= date_from)
    if date_to is not None:
        conditions.append(AuditLog.created_at <= date_to)
    return conditions


def _audit_query(
    db: Session,
    *,
    action: str | None,
    actor_user_id: int | None,
    entity_type: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    sort: str,
):
    stmt = select(AuditLog).where(*_audit_filter_conditions(
        action=action,
        actor_user_id=actor_user_id,
        entity_type=entity_type,
        date_from=date_from,
        date_to=date_to,
    ))
    if sort == "asc":
        stmt = stmt.order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
    else:
        stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    return stmt


def _audit_filter_args(
    action: str | None,
    actor_user_id: int | None,
    entity_type: str | None,
    date_from: str | None,
    date_to: str | None,
    sort: str,
) -> dict[str, Any]:
    return {
        "action": action,
        "actor_user_id": actor_user_id,
        "entity_type": entity_type,
        "date_from": date_from,
        "date_to": date_to,
        "sort": sort,
    }


@router.get("/admin/audit", response_class=HTMLResponse)
def admin_audit_page(
    request: Request,
    action: str | None = None,
    actor_user_id: int | None = None,
    entity_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str = "desc",
    page: int = 1,
    per_page: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
):
    sort = "asc" if sort == "asc" else "desc"
    page = max(1, page)
    per_page = max(1, min(per_page, 200))
    df = _parse_audit_date(date_from)
    dt = _parse_audit_date(date_to)
    conditions = _audit_filter_conditions(
        action=action,
        actor_user_id=actor_user_id,
        entity_type=entity_type,
        date_from=df,
        date_to=dt,
    )
    base = _audit_query(
        db,
        action=action,
        actor_user_id=actor_user_id,
        entity_type=entity_type,
        date_from=df,
        date_to=dt,
        sort=sort,
    )
    total = db.scalar(select(func.count(AuditLog.id)).where(*conditions)) or 0
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    offset = (page - 1) * per_page
    rows = list(db.scalars(base.offset(offset).limit(per_page)))
    actor_ids = {row.actor_user_id for row in rows if row.actor_user_id is not None}
    actor_map: dict[int, User] = {}
    if actor_ids:
        actor_map = {
            user.id: user
            for user in db.scalars(select(User).where(User.id.in_(actor_ids)))
        }
    actions = [a for a in db.scalars(select(distinct(AuditLog.action)).order_by(AuditLog.action)) if a]
    entity_types = [t for t in db.scalars(select(distinct(AuditLog.entity_type)).order_by(AuditLog.entity_type)) if t]
    users = list(db.scalars(select(User).order_by(User.display_name)))
    unique_actors = db.scalar(
        select(func.count(distinct(AuditLog.actor_user_id))).where(*conditions)
    ) or 0
    unique_actions = db.scalar(
        select(func.count(distinct(AuditLog.action))).where(*conditions)
    ) or 0
    return templates.TemplateResponse(
        request,
        "admin/audit.html",
        template_context(
            request,
            db=db,
            current_user=current_user,
            logs=rows,
            actor_map=actor_map,
            actions=actions,
            entity_types=entity_types,
            users=users,
            filters=_audit_filter_args(action, actor_user_id, entity_type, date_from, date_to, sort),
            pagination={
                "page": page,
                "pages": pages,
                "total": total,
                "per_page": per_page,
                "has_prev": page > 1,
                "has_next": page < pages,
                "prev_num": page - 1,
                "next_num": page + 1,
            },
            stats={
                "total": total,
                "unique_actors": unique_actors,
                "unique_actions": unique_actions,
            },
        ),
    )


@router.get("/admin/audit/data")
def admin_audit_data(
    action: str | None = None,
    actor_user_id: int | None = None,
    entity_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str = "desc",
    page: int = 1,
    per_page: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
):
    sort = "asc" if sort == "asc" else "desc"
    page = max(1, page)
    per_page = max(1, min(per_page, 200))
    base = _audit_query(
        db,
        action=action,
        actor_user_id=actor_user_id,
        entity_type=entity_type,
        date_from=_parse_audit_date(date_from),
        date_to=_parse_audit_date(date_to),
        sort=sort,
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    offset = (page - 1) * per_page
    rows = list(db.scalars(base.offset(offset).limit(per_page)))
    actor_ids = {row.actor_user_id for row in rows if row.actor_user_id is not None}
    actor_map: dict[int, User] = {}
    if actor_ids:
        actor_map = {
            user.id: user
            for user in db.scalars(select(User).where(User.id.in_(actor_ids)))
        }
    logs_data = []
    for log in rows:
        actor = actor_map.get(log.actor_user_id) if log.actor_user_id else None
        logs_data.append({
            "id": log.id,
            "created_at": log.created_at.strftime("%d.%m.%Y %H:%M:%S") if log.created_at else "",
            "actor_email": actor.email if actor else "System",
            "actor_name": actor.display_name if actor else "System",
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "before_json": log.before_json,
            "after_json": log.after_json,
        })
    return JSONResponse({
        "logs": logs_data,
        "pagination": {
            "page": page,
            "pages": pages,
            "total": total,
            "per_page": per_page,
            "has_prev": page > 1,
            "has_next": page < pages,
            "prev_num": page - 1,
            "next_num": page + 1,
        },
        "sort": sort,
    })


@router.get("/admin/audit/export/csv")
def admin_audit_export_csv(
    action: str | None = None,
    actor_user_id: int | None = None,
    entity_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str = "desc",
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
):
    sort = "asc" if sort == "asc" else "desc"
    base = _audit_query(
        db,
        action=action,
        actor_user_id=actor_user_id,
        entity_type=entity_type,
        date_from=_parse_audit_date(date_from),
        date_to=_parse_audit_date(date_to),
        sort=sort,
    )
    rows = list(db.scalars(base.limit(10000)))
    actor_ids = {row.actor_user_id for row in rows if row.actor_user_id is not None}
    actor_map: dict[int, User] = {}
    if actor_ids:
        actor_map = {
            user.id: user
            for user in db.scalars(select(User).where(User.id.in_(actor_ids)))
        }
    buf = StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow([
        "Zeitstempel",
        "Akteur",
        "Aktion",
        "Ressourcentyp",
        "Ressourcen-ID",
        "Vorher",
        "Nachher",
    ])
    for log in rows:
        actor = actor_map.get(log.actor_user_id) if log.actor_user_id else None
        writer.writerow([
            log.created_at.strftime("%d.%m.%Y %H:%M:%S") if log.created_at else "",
            actor.email if actor else "System",
            log.action,
            log.entity_type or "",
            log.entity_id if log.entity_id is not None else "",
            json.dumps(log.before_json, ensure_ascii=False) if log.before_json is not None else "",
            json.dumps(log.after_json, ensure_ascii=False) if log.after_json is not None else "",
        ])
    filename = f"audit_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
