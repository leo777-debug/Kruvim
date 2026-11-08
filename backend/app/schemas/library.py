from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=240)
    data: str = Field(min_length=1, max_length=10000)
    region: str = Field(default="*", max_length=16)
    language: str = Field(default="", max_length=20)
    tags: str = Field(default="", max_length=500)

    @field_validator("region")
    @classmethod
    def supported_region(cls, value):
        from app.services.population.regions import CONTEXT_CODES
        if value != "*" and value not in CONTEXT_CODES:
            raise ValueError("Choose a supported region or * for all regions.")
        return value


class FolderIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=160)
    project_id: str | None = None
    enabled: bool = True
    watch_enabled: bool = False
    visibility: Literal["private", "public", "baseline"] = "private"
    publish_confirmed: bool = False

    @model_validator(mode="after")
    def shared_scope(self):
        if self.visibility != "private" and self.project_id:
            raise ValueError("Public and admin baseline folders apply across projects.")
        return self
