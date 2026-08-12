from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from postbuch.core.utils import slugify
from postbuch.models.category import Category
from postbuch.models.category_proposal import CategoryProposal
from postbuch.models.enums import ProposalStatus, Role
from postbuch.models.user import User
from postbuch.schemas.category import CategoryCreate, CategoryProposalCreate
from postbuch.services.audit import create_audit_entry


def list_categories(db: Session) -> list[Category]:
    stmt: Select[tuple[Category]] = select(Category).where(Category.is_active.is_(True)).order_by(Category.name)
    return list(db.scalars(stmt))


def create_category(db: Session, *, current_user: User, payload: CategoryCreate) -> Category:
    if current_user.role not in {Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR}:
        raise PermissionError("Only admins/editors can create categories.")

    name = payload.name.strip()
    if not name:
        raise ValueError("Kategorie-Name ist erforderlich.")
    slug = slugify(name)
    if not slug:
        raise ValueError("Kategorie-Name ist ungültig.")

    duplicate = db.scalar(
        select(Category).where(
            or_(
                func.lower(Category.name) == name.lower(),
                Category.slug == slug,
            )
        )
    )
    if duplicate is not None:
        raise ValueError("Kategorie existiert bereits.")

    category = Category(
        name=name,
        slug=slug,
        description=(payload.description or "").strip() or None,
        is_active=True,
        created_by_user_id=current_user.id,
        approved_by_user_id=current_user.id,
    )
    db.add(category)
    db.flush()
    create_audit_entry(
        db,
        entity_type="category",
        entity_id=category.id,
        action="created",
        actor_user_id=current_user.id,
        before_json=None,
        after_json={"name": category.name, "slug": category.slug},
    )
    db.commit()
    db.refresh(category)
    return category


def create_proposal(db: Session, *, current_user: User, payload: CategoryProposalCreate) -> CategoryProposal:
    proposal = CategoryProposal(
        proposed_name=payload.proposed_name.strip(),
        normalized_slug=slugify(payload.proposed_name),
        proposal_reason=payload.proposal_reason,
        proposed_by_user_id=current_user.id,
    )
    db.add(proposal)
    db.flush()
    create_audit_entry(
        db,
        entity_type="category_proposal",
        entity_id=proposal.id,
        action="proposal_created",
        actor_user_id=current_user.id,
        before_json=None,
        after_json={"proposed_name": proposal.proposed_name},
    )
    db.commit()
    db.refresh(proposal)
    return proposal


def review_proposal(db: Session, *, proposal: CategoryProposal, current_user: User, approve: bool) -> CategoryProposal:
    if current_user.role != Role.SUPER_ADMIN:
        raise PermissionError("Only super admins can review proposals.")
    before = {"status": proposal.status}
    proposal.status = ProposalStatus.APPROVED if approve else ProposalStatus.REJECTED
    proposal.reviewed_by_user_id = current_user.id
    proposal.reviewed_at = datetime.now(timezone.utc)
    if approve and proposal.linked_category_id is None:
        category = Category(
            name=proposal.proposed_name.strip(),
            slug=proposal.normalized_slug,
            created_by_user_id=proposal.proposed_by_user_id,
            approved_by_user_id=current_user.id,
        )
        db.add(category)
        db.flush()
        proposal.linked_category_id = category.id
    create_audit_entry(
        db,
        entity_type="category_proposal",
        entity_id=proposal.id,
        action="proposal_approved" if approve else "proposal_rejected",
        actor_user_id=current_user.id,
        before_json=before,
        after_json={"status": proposal.status},
    )
    db.commit()
    db.refresh(proposal)
    return proposal
