"""Runtime configuration. Every value can be set with a KRUVIM_* environment variable or .env file."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KRUVIM_", env_file=(".env", "../.env"), extra="ignore")

    env: str = "development"                       # development | production | test
    app_name: str = "Kruvim"
    secret_key: str = "dev-insecure-change-me"     # JWT signing + secret encryption (derive per purpose)
    public_url: str = "http://localhost:5173"

    database_url: str = f"sqlite+aiosqlite:///{os.path.join(_BACKEND_ROOT, 'data', 'kruvim.db')}"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    redis_url: str | None = None                    # unset = single-process dev mode (in-memory queue + events)

    data_dir: str = os.path.join(_BACKEND_ROOT, "data")
    storage_backend: str = "local"                  # local | s3
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    max_upload_mb: int = 500

    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])
    access_token_minutes: int = 30
    refresh_token_days: int = 14
    allow_registration: bool = True
    first_superuser_email: str | None = None
    first_superuser_password: str | None = None

    rate_limit_per_minute: int = 240               # per user / API key / IP
    rate_limit_auth_per_minute: int = 20

    population_size: int = 1_000_000
    population_seed: int = 7

    worker_max_jobs: int = 4
    org_max_concurrent_default: int = 2

    # Platform-wide default model provider (orgs can bring their own). Blank = dry run.
    llm_preset: str = "dryrun"
    llm_provider: str = "dryrun"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_voice_model: str = ""
    llm_report_model: str = ""
    llm_vision_model: str = ""
    llm_concurrency: int = 8

    # Data pool connector credentials (all optional)
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    youtube_api_key: str = ""
    x_bearer_token: str = ""
    bluesky_handle: str = ""
    bluesky_app_password: str = ""
    datapool_refresh_minutes: int = 60

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_prod(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_prod and s.secret_key.startswith("dev-"):
        raise RuntimeError("KRUVIM_SECRET_KEY must be set in production")
    os.makedirs(s.data_dir, exist_ok=True)
    return s


settings = get_settings()
