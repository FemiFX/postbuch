from datetime import datetime

from pydantic import BaseModel, EmailStr

from postbuch.models.enums import Role
from postbuch.schemas.common import ORMModel


class UserRead(ORMModel):
    id: int
    email: EmailStr
    display_name: str
    role: Role
    is_active: bool
    last_login_at: datetime | None


class UserCreate(BaseModel):
    email: EmailStr
    display_name: str
    role: Role = Role.VIEWER
    is_active: bool = True


class UserUpdate(BaseModel):
    display_name: str
    role: Role
    is_active: bool


class TriageAssigneeRead(ORMModel):
    id: int
    email: EmailStr
    display_name: str
    is_active: bool


class UserRoleUpdate(BaseModel):
    role: Role


class UserActiveUpdate(BaseModel):
    is_active: bool
