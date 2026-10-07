import math
import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class FollowerSplit(BaseModel):
    countries: dict[str, float] = Field(default_factory=dict, max_length=250)
    ages: dict[str, float] = Field(default_factory=dict, max_length=20)
    genders: dict[Literal["female", "male", "unknown"], float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_percentages(self):
        for name in ("countries", "ages", "genders"):
            values = getattr(self, name)
            if values and (any(not math.isfinite(v) or v < 0 or v > 100 for v in values.values()) or abs(sum(values.values()) - 100) > 1):
                raise ValueError(f"{name}: enter percentages adding to 100 (within 1%).")
        for key in self.countries:
            if not re.fullmatch(r"[A-Z]{2}", key):
                raise ValueError("Countries must use two-letter uppercase codes, such as SA or AE.")
        for key in self.ages:
            match = re.fullmatch(r"(\d{1,2})(?:-(\d{1,2})|\+)", key)
            if not match or (match[2] and int(match[1]) > int(match[2])):
                raise ValueError("Age bands must look like 18-24 or 65+.")
        bands = [(int(k.split('-')[0].rstrip('+')), int(k.split('-')[1]) if '-' in k else 120) for k in self.ages]
        bands.sort()
        if any(bands[i][1] >= bands[i+1][0] for i in range(len(bands)-1)):
            raise ValueError("Age bands must not overlap.")
        return self


class AudienceProfileIn(BaseModel):
    split: FollowerSplit
    label: str = Field(default="My audience", max_length=200)
    filters: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_filters(self):
        from app.schemas.simulation import AudienceIn
        allowed = {"emirates", "nationality_groups", "income_bands", "languages", "include_visitors"}
        if set(self.filters) - allowed:
            raise ValueError("My audience filters support only UAE attributes and the visitor toggle")
        validated = AudienceIn.model_validate(self.filters)
        self.filters = {k: validated.model_dump()[k] for k in allowed}
        return self


class PostLinkIn(BaseModel):
    connection_id: str
    variant: Literal["A", "B"] = "A"
    post_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")


class ConsentIn(BaseModel):
    share_accuracy: bool


class MemoryResetIn(BaseModel):
    confirmed: Literal[True]
    subject: str | None = Field(default=None, max_length=160)
