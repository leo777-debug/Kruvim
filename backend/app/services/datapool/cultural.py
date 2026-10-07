"""One scheduled stronger-model synthesis per region/day, outside simulation billing."""
import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.base import utcnow
from app.db.session import session_scope
from app.models import CulturalMoment
from app.services.llm import Usage, make_llm
from app.services.providers import resolve

from .context import all_codes, build_snapshot_data, template_brief

SYSTEM = "Read only the supplied regional signals. Summarize today's cultural mood, sensitivities, what is overdone, and what may resonate. " \
         "Do not invent trends or facts. Mention uncertainty. Return JSON {\"note\": \"up to 90 words\"}."


async def synthesize_daily():
    day = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    async with session_scope() as s:
        provider = await resolve(s, None)
    llm = make_llm(provider.settings)
    try:
        for code in all_codes():
            async with session_scope() as s:
                if (await s.execute(select(CulturalMoment.id).where(CulturalMoment.region == code, CulturalMoment.day == day))).first():
                    continue
            data = await build_snapshot_data(code, utcnow())
            row = CulturalMoment(region=code, day=day, note=template_brief(data), model="template")
            # Reserve the daily entry before the model call so concurrent schedulers cannot double-spend.
            try:
                async with session_scope() as s:
                    s.add(row)
            except IntegrityError:
                continue
            if llm.is_dry:
                continue
            usage = Usage()
            try:
                output = await llm.complete_json(system=SYSTEM, user=json.dumps({k: data.get(k) for k in ("news", "social", "trending", "tone", "events")}, default=str),
                                                 role="report", max_tokens=350, usage=usage)
                note = str(output.get("note", "")).strip()[:1200]
                if note:
                    async with session_scope() as s:
                        saved = await s.get(CulturalMoment, row.id)
                        saved.note, saved.model, saved.usage = note, llm.model_for("report"), usage.as_dict(provider.settings)
            except Exception:
                pass  # retain a reproducible template, never retry a model call this day
    finally:
        await llm.aclose()
