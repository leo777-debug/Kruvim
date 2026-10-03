"""Which model provider a given organisation uses: its own default config (bring-your-own key),
else the platform default (Kruvim's key, metered in credits), else the environment, else dry run."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import decrypt
from app.models import ProviderConfig
from app.services.llm import ProviderSettings


@dataclass
class Resolved:
    settings: ProviderSettings
    source: str          # org | platform | env | dryrun
    config_id: str | None

    @property
    def metered(self) -> bool:
        return self.source in ("platform", "env") and self.settings.provider != "dryrun"


def to_settings(c: ProviderConfig) -> ProviderSettings:
    return ProviderSettings(provider=c.provider, preset=c.preset, base_url=c.base_url or "", api_key=decrypt(c.api_key_enc),
                            voice_model=c.voice_model or "", report_model=c.report_model or "", vision_model=c.vision_model or "",
                            concurrency=c.concurrency or 6, temperature=c.temperature if c.temperature is not None else 0.9,
                            json_mode=bool(c.json_mode), price_in=c.price_in, price_cached=c.price_cached, price_out=c.price_out)


async def resolve(s: AsyncSession, org_id: str | None) -> Resolved:
    if org_id:
        c = (await s.execute(select(ProviderConfig).where(and_(ProviderConfig.org_id == org_id, ProviderConfig.is_default.is_(True)))
                             .order_by(ProviderConfig.created_at.desc()).limit(1))).scalar_one_or_none()
        if c is not None:
            return Resolved(to_settings(c), "org", c.id)
    c = (await s.execute(select(ProviderConfig).where(and_(ProviderConfig.org_id.is_(None), ProviderConfig.is_default.is_(True)))
                         .order_by(ProviderConfig.created_at.desc()).limit(1))).scalar_one_or_none()
    if c is not None:
        return Resolved(to_settings(c), "platform", c.id)
    if settings.llm_provider != "dryrun":
        return Resolved(ProviderSettings(provider=settings.llm_provider, preset=settings.llm_preset, base_url=settings.llm_base_url,
                                         api_key=settings.llm_api_key, voice_model=settings.llm_voice_model,
                                         report_model=settings.llm_report_model, vision_model=settings.llm_vision_model,
                                         concurrency=settings.llm_concurrency), "env", None)
    return Resolved(ProviderSettings(), "dryrun", None)
