from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.creator import FollowerSplit

ContentType = Literal["video", "audio", "image", "text"]


class VariantIn(BaseModel):
    type: ContentType | None = None
    title: str = Field(default="", max_length=300)
    text: str = Field(default="", max_length=60_000)
    transcript: str = Field(default="", max_length=120_000)
    description: str = Field(default="", max_length=8000)
    asset_id: str | None = None
    asset_ids: list[str] = Field(default_factory=list, max_length=10)        # carousel slides, in order
    poll_options: list[str] = Field(default_factory=list, max_length=6)


class ContentIn(VariantIn):
    type: ContentType = "text"
    format: str | None = Field(default=None, max_length=40)                   # see services/content/formats.py
    platform: str = "tiktok"
    goal: str = Field(default="", max_length=300)
    creator_followers: int | None = Field(default=None, ge=0, le=2_000_000_000)   # only used to scale reach to real people
    creator_subject: str = Field(default="workspace", min_length=1, max_length=120)
    seed_asset_ids: list[str] = Field(default_factory=list, max_length=20)
    variant_b: VariantIn | None = None
    b_kind: Literal["version", "competitor"] = "version"                      # A/B test or benchmark against a competitor's content

    @model_validator(mode="after")
    def _format(self):
        from app.services.content.formats import FORMATS, resolve
        self.format = resolve(self.format, self.type)
        self.type = FORMATS[self.format]["type"]
        self.poll_options = [o.strip()[:120] for o in self.poll_options if o.strip()]
        if FORMATS[self.format].get("poll") and len(self.poll_options) < 2:
            raise ValueError("A poll needs at least two options.")
        return self


class AudienceIn(BaseModel):
    follower_split: FollowerSplit | None = None
    use_creator_audience: bool = False
    regions: list[str] = Field(default_factory=list)
    age_min: int | None = Field(default=None, ge=16, le=70)
    age_max: int | None = Field(default=None, ge=16, le=70)
    genders: list[Literal["female", "male"]] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    citizens_only: bool = False
    stances: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    education_min: int | None = Field(default=None, ge=0, le=3)
    professions: list[str] = Field(default_factory=list)
    incomes: list[str] = Field(default_factory=list)
    expats_only: bool = False
    ocean: dict[Literal["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"], tuple[float, float]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _ranges(self):
        if self.age_min is not None and self.age_max is not None and self.age_min > self.age_max:
            raise ValueError("The minimum age is higher than the maximum age.")
        for k, (lo, hi) in self.ocean.items():
            if not (0 <= lo <= hi <= 1):
                raise ValueError(f"{k}: the range must satisfy 0 <= min <= max <= 1.")
        if self.citizens_only and self.expats_only:
            raise ValueError("Choose citizens only or expatriates only, not both.")
        return self


class OverridesIn(BaseModel):
    voice: int = Field(default=80, ge=10, le=2000)
    crowd: int = Field(default=3000, ge=0, le=250_000)
    stakeholders: int = Field(default=5, ge=0, le=30)
    hours: int = Field(default=24, ge=1, le=336)
    minutes_per_round: int = Field(default=60, ge=15, le=240)
    platforms: list[Literal["feed", "forum"]] = Field(default_factory=lambda: ["feed", "forum"])
    listening: bool = True
    seed: int | None = None
    returning_share: float | None = Field(default=None, ge=0, le=1)
    fresh_audience: bool = False


class SimulationCreate(BaseModel):
    name: str = Field(default="Untitled simulation", max_length=200)
    requirement: str = Field(default="", max_length=4000)
    content: ContentIn
    audience: AudienceIn = Field(default_factory=AudienceIn)
    publish_at: datetime | None = None
    overrides: OverridesIn = Field(default_factory=OverridesIn)


class SimulationUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    requirement: str | None = Field(default=None, max_length=4000)
    content: ContentIn | None = None
    audience: AudienceIn | None = None
    publish_at: datetime | None = None
    overrides: OverridesIn | None = None


class ConfigPatch(BaseModel):
    platforms: dict | None = None
    events: dict | None = None
    time: dict | None = None
    analysis_focus: str | None = None
    external_seed: list | None = None


class ControlIn(BaseModel):
    cmd: Literal["pause", "resume", "stop", "inject", "speed"]
    text: str | None = Field(default=None, max_length=400)
    value: float | None = None


class CloneIn(BaseModel):
    mode: Literal["edit", "rerun"] = "edit"
    changes: dict = Field(default_factory=dict)        # applied to version B, e.g. {"title": "..."}
    build: bool = False                                 # start building the knowledge graph right away

    @model_validator(mode="after")
    def _allowed(self):
        allowed = {"title", "text", "transcript", "description"}
        self.changes = {k: str(v)[:60_000] for k, v in self.changes.items() if k in allowed}
        return self


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class SurveyIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    region: str | None = None
    stance: str | None = None
    kind: Literal["voice", "stakeholder"] | None = None
    n: int = Field(default=12, ge=1, le=2000)
    everyone: bool = False
    confirmed_count: int | None = Field(default=None, ge=1, le=2000)
    confirmed_credits: int | None = Field(default=None, ge=0)


class ExploreIn(AudienceIn):
    pass
