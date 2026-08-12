from typing import Literal

from pydantic import BaseModel


class ForwardingTemplateRead(BaseModel):
    id: int
    forwarding_route_id: int
    name: str
    subject_template: str
    body_template: str
    is_default: bool
    is_active: bool

    model_config = {"from_attributes": True}


class ForwardingTemplateCreate(BaseModel):
    name: str
    subject_template: str
    body_template: str
    is_default: bool = False


class ForwardingTemplateUpdate(BaseModel):
    name: str | None = None
    subject_template: str | None = None
    body_template: str | None = None
    is_default: bool | None = None
    is_active: bool | None = None


class ForwardingRouteRead(BaseModel):
    id: int
    name: str
    description: str | None
    target_email: str | None
    is_active: bool
    sort_order: int
    templates: list[ForwardingTemplateRead] = []

    model_config = {"from_attributes": True}


class ForwardingRouteCreate(BaseModel):
    name: str
    description: str | None = None
    target_email: str | None = None
    sort_order: int = 0


class ForwardingRouteUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    target_email: str | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class ForwardActionPayload(BaseModel):
    target_type: Literal["route", "user", "external", "reply"]
    route_id: int | None = None
    user_id: int | None = None
    external_email: str | None = None
    template_id: int | None = None
    message_subject: str | None = None
    message_body: str | None = None
    note: str | None = None
    after_status: Literal["weitergeleitet", "wartet_aktion", "beantwortet"] = "weitergeleitet"
