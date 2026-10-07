from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

_EMAIL = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$")


def _email(v: str) -> str:
    # Syntax only: self-hosted installs use internal domains (.local, .corp, .internal) that
    # email-validator rejects as special-use. Lower-cased so lookups are case-insensitive.
    v = v.strip().lower()
    local = v.split("@", 1)[0]
    if not _EMAIL.match(v) or local.startswith(".") or local.endswith(".") or ".." in local:
        raise ValueError("Enter a valid email address")
    return v


Email = Annotated[str, Field(max_length=320), AfterValidator(_email)]


class RegisterIn(BaseModel):
    email: Email
    password: str = Field(min_length=10, max_length=200)
    name: str = Field(default="", max_length=200)
    org_name: str = Field(default="", max_length=200)


class LoginIn(BaseModel):
    email: Email
    password: str = Field(max_length=200)


class RefreshIn(BaseModel):
    refresh_token: str


class AcceptInviteIn(BaseModel):
    token: str
    name: str = ""
    password: str | None = Field(default=None, min_length=10, max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)


class OrgOut(BaseModel):
    id: str
    name: str
    slug: str
    plan: str
    role: str
    credits_balance: int


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    is_superuser: bool


class SessionOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
    orgs: list[OrgOut]
