"""Regional context at a moment in time: the hourly snapshot every agent is conditioned on.

* `now` (or a near-future publish time): latest signals, refreshed on demand when stale.
* a past time: the archived snapshot nearest before it (backtesting against what people saw then).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, desc, select

from app.db.base import utcnow
from app.db.session import session_scope
from app.models import RegionSnapshot, Signal
from app.services.llm import BaseLLM, Usage
from app.services.population.regions import REGIONS, region

from .runner import run_connector

log = logging.getLogger("kruvim.datapool")
ON_DEMAND = ["open_meteo", "google_news", "wikipedia", "calendar"]


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def hour_bucket(dt: datetime) -> datetime:
    dt = _aware(dt)
    return dt.replace(minute=0, second=0, microsecond=0)


async def _latest(s, region_code: str, kinds: list[str], since: datetime, limit: int, scope_global=False):
    regs = [region_code, "*"] if scope_global else [region_code]
    q = (select(Signal).where(and_(Signal.region.in_(regs), Signal.kind.in_(kinds), Signal.fetched_at >= since))
         .order_by(desc(Signal.fetched_at), desc(Signal.value)).limit(limit))
    return (await s.execute(q)).scalars().all()


async def build_snapshot_data(code: str, at: datetime) -> dict:
    async with session_scope() as s:
        w = await _latest(s, code, ["weather"], at - timedelta(hours=3), 1)
        tone = await _latest(s, code, ["tone"], at - timedelta(hours=30), 1)
        news = await _latest(s, code, ["headline"], at - timedelta(hours=24), 12)
        trends = await _latest(s, code, ["trend"], at - timedelta(hours=48), 10)
        social = await _latest(s, code, ["social_trend"], at - timedelta(hours=24), 12, scope_global=True)
        events = await _latest(s, code, ["event"], at - timedelta(hours=36), 5)
        econ = await _latest(s, code, ["economy"], at - timedelta(hours=36), 2)
    reg = region(code)
    local = at + timedelta(hours=reg["tz_offset"])
    return {
        "region": code, "name": reg["name"], "city": reg["city"], "at": at.isoformat(),
        "local_time": local.strftime("%a %H:%M"), "local_hour": local.hour,
        "weather": w[0].payload if w else None,
        "tone": ({"avg": tone[0].value, **tone[0].payload} if tone else None),
        "news": [{"title": x.title, "source": x.payload.get("source", ""), "url": x.url} for x in news],
        "trending": [{"title": x.title, "views": x.value} for x in trends],
        "social": [{"title": x.title, "platform": x.payload.get("platform"), "value": x.value, "url": x.url} for x in social],
        "events": sorted([{"name": x.title, **x.payload} for x in events], key=lambda e: e.get("days_away", 99)),
        "economy": [{"title": x.title, "value": x.value} for x in econ],
    }


def template_brief(d: dict) -> str:
    parts = [f"{d['city']}, {d['local_time']} local time."]
    w = d.get("weather")
    if w:
        parts.append(f"{w['temp_c']:.0f}°C (feels {w['feels_c']:.0f}°C), {w['text']}.")
    t = d.get("tone")
    if t and t.get("avg") is not None:
        mood = "sharply negative" if t["avg"] < -4 else "negative" if t["avg"] < -2 else "mixed" if t["avg"] < 0.5 else "positive"
        parts.append(f"Local news tone is {mood} ({t['avg']:+.1f}).")
    if d.get("news"):
        parts.append("Top stories: " + "; ".join(n["title"] for n in d["news"][:3]) + ".")
    if d.get("trending"):
        parts.append("Most read: " + ", ".join(x["title"] for x in d["trending"][:4]) + ".")
    if d.get("events"):
        e = d["events"][0]
        parts.append(f"Coming up: {e['name']} in {e.get('days_away', '?')} days.")
    return " ".join(parts)


BRIEF_SYSTEM = (
    "You write short situational briefs used to condition simulated social-media users. For each region write 3-4 plain "
    "sentences (max 90 words) on what a typical resident plausibly has on their mind at the given local time: weather "
    "comfort, the 2-3 dominant stories (paraphrased in English), the mood implied by news tone, any upcoming holiday, and "
    "what is trending socially. No speculation beyond the data, no advice, no bullet points.\n"
    'Return JSON: {"briefs": {"<REGION CODE>": "<brief>"}}'
)


async def ensure_fresh(codes: list[str]) -> None:
    """Run keyless connectors on demand when the pool has nothing recent for these regions."""
    since = utcnow() - timedelta(hours=2)
    async with session_scope() as s:
        have = {r for (r,) in (await s.execute(select(Signal.region).where(
            and_(Signal.region.in_(codes), Signal.kind == "weather", Signal.fetched_at >= since)).distinct())).all()}
    missing = [c for c in codes if c not in have]
    if missing:
        for key in ON_DEMAND:
            await run_connector(key, missing)


async def snapshots_at(codes: list[str], at: datetime | None, llm: BaseLLM | None = None, usage: Usage | None = None) -> dict[str, dict]:
    """Snapshot per region for the given moment (creates and archives it if needed)."""
    now = utcnow()
    at = _aware(at) if at else now
    historical = at < now - timedelta(hours=2)
    out: dict[str, dict] = {}
    if historical:
        async with session_scope() as s:
            for c in codes:
                row = (await s.execute(select(RegionSnapshot).where(and_(RegionSnapshot.region == c, RegionSnapshot.hour <= at))
                                       .order_by(desc(RegionSnapshot.hour)).limit(1))).scalar_one_or_none()
                if row:
                    out[c] = {**row.data, "brief": row.brief, "brief_by": row.brief_by, "archived": True}
        missing = [c for c in codes if c not in out]
        if not missing:
            return out
        codes = missing
    await ensure_fresh(codes)
    bucket = hour_bucket(now)
    need_brief = []
    async with session_scope() as s:
        for c in codes:
            row = (await s.execute(select(RegionSnapshot).where(and_(RegionSnapshot.region == c, RegionSnapshot.hour == bucket)))).scalar_one_or_none()
            if row is None:
                data = await build_snapshot_data(c, now)
                row = RegionSnapshot(region=c, hour=bucket, data=data, brief=template_brief(data), brief_by="template")
                s.add(row)
                await s.flush()
            out[c] = {**row.data, "brief": row.brief, "brief_by": row.brief_by, "archived": False}
            if row.brief_by == "template":
                need_brief.append(c)
    if at > now + timedelta(hours=1):   # scheduled publish time: same live context, shifted clock + calendar
        for c in codes:
            reg = region(c)
            local = at + timedelta(hours=reg["tz_offset"])
            out[c]["scheduled_local_time"] = local.strftime("%a %d %b %H:%M")
            out[c]["brief"] += f" (Content will be published {local.strftime('%a %H:%M')} local time.)"
    if need_brief and llm is not None and not llm.is_dry:
        await _llm_briefs(out, need_brief, llm, usage or Usage(), bucket)
    return out


async def _llm_briefs(out: dict, codes: list[str], llm: BaseLLM, usage: Usage, bucket: datetime) -> None:
    payload = [{"region": c, "city": out[c]["city"], "local_time": out[c]["local_time"], "weather": out[c].get("weather"),
                "headlines": [n["title"] for n in out[c].get("news", [])[:10]], "news_tone": out[c].get("tone"),
                "most_read": [t["title"] for t in out[c].get("trending", [])[:8]],
                "social_trends": [t["title"] for t in out[c].get("social", [])[:8]], "upcoming": out[c].get("events")} for c in codes]
    try:
        data = await llm.complete_json(system=BRIEF_SYSTEM, user=json.dumps(payload, ensure_ascii=False, default=str),
                                       role="brief", max_tokens=1800, usage=usage)
        briefs = data.get("briefs", data) if isinstance(data, dict) else {}
    except Exception as exc:
        log.warning("brief generation failed: %s", exc)
        return
    async with session_scope() as s:
        for c in codes:
            b = briefs.get(c)
            if isinstance(b, str) and b.strip():
                row = (await s.execute(select(RegionSnapshot).where(and_(RegionSnapshot.region == c, RegionSnapshot.hour == bucket)))).scalar_one_or_none()
                if row:
                    row.brief, row.brief_by = b.strip(), llm.model_for("brief")
                out[c]["brief"], out[c]["brief_by"] = b.strip(), llm.model_for("brief")


# ---- trend alignment -------------------------------------------------------------------------------------
_STOP = set("""a an the and or but of to in on for with at by from is are was were be been this that these those it its as into about
over after before than then there their they them you your our we he she his her not no yes can will just more most very new how
what why when who which video watch here have has had do does did get got make made من في على إلى عن مع هذا هذه التي الذي""".split())


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[\w؀-ۿ]{4,}", (text or "").lower()) if w not in _STOP and not w.isdigit()}


def trend_alignment(card: dict, snaps: dict) -> dict:
    bag = " ".join([card.get("title") or "", card.get("summary") or "", " ".join(card.get("entities") or []),
                    " ".join(card.get("keywords") or []), " ".join(s.get("text", "")[:400] for s in card.get("segments", []))])
    ct = tokens(bag)
    matches = []
    for code, s in snaps.items():
        items = [("news", n["title"]) for n in s.get("news", [])] + [("trending", t["title"]) for t in s.get("trending", [])] \
            + [("social", t["title"]) for t in s.get("social", [])]
        for kind, title in items:
            ov = ct & tokens(title)
            if ov:
                matches.append({"region": code, "kind": kind, "title": title, "overlap": sorted(ov)[:6], "strength": len(ov)})
    matches.sort(key=lambda m: -m["strength"])
    strength = sum(min(m["strength"], 3) for m in matches[:8])
    return {"score": round(min(1.0, strength / 10), 3), "matches": matches[:12],
            "method": "keyword overlap between the content and live headlines, most-read pages and social trends"}


def all_codes() -> list[str]:
    return [r["code"] for r in REGIONS]
