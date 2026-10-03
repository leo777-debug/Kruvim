from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.auth import Email

Role = Literal["owner", "admin", "member", "viewer"]


class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class OrgUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)


class InviteIn(BaseModel):
    email: Email
    role: Role = "member"


class MemberUpdate(BaseModel):
    role: Role


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: Literal["admin", "member", "viewer"] = "member"


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    archived: bool | None = None


class ProviderIn(BaseModel):
    name: str = "Default"
    preset: str = "dryrun"
    base_url: str = ""
    api_key: str | None = None          # None = keep; "" = clear
    voice_model: str = ""
    report_model: str = ""
    vision_model: str = ""
    concurrency: int = Field(default=6, ge=1, le=64)
    temperature: float = Field(default=0.9, ge=0, le=2)
    json_mode: bool = True
    price_in: float | None = None
    price_cached: float | None = None
    price_out: float | None = None


class PerformanceIn(BaseModel):
    variant: Literal["A", "B"] = "A"
    platform: str = ""
    views: int | None = Field(default=None, ge=0)
    likes: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    ctr: float | None = Field(default=None, ge=0, le=100)
    engagement_rate: float | None = Field(default=None, ge=0, le=100)
    retention: float | None = Field(default=None, ge=0, le=100)
    notes: str = Field(default="", max_length=2000)


class AdminOrgUpdate(BaseModel):
    plan: Literal["free", "pro", "business", "enterprise"] | None = None
    credits_delta: int | None = None
    max_concurrent: int | None = Field(default=None, ge=1, le=500)


class Page(BaseModel):
    items: list
    total: int | None = None
    next_cursor: str | None = None


class Timestamped(BaseModel):
    created_at: datetime
