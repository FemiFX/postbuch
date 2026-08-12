from datetime import datetime

from pydantic import BaseModel

from postbuch.models.enums import ProposalStatus
from postbuch.schemas.common import ORMModel


class CategoryRead(ORMModel):
    id: int
    name: str
    slug: str
    description: str | None
    is_active: bool


class CategoryCreate(BaseModel):
    name: str
    description: str | None = None


class CategoryProposalCreate(BaseModel):
    proposed_name: str
    proposal_reason: str | None = None


class CategoryProposalRead(ORMModel):
    id: int
    proposed_name: str
    normalized_slug: str
    proposal_reason: str | None
    status: ProposalStatus
    proposed_by_user_id: int
    reviewed_by_user_id: int | None
    linked_category_id: int | None
    created_at: datetime
