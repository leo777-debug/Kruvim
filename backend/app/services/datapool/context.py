"""Regional context at a moment in time: the hourly snapshot every agent is conditioned on.

* `now` (or a near-future publish time): latest signals, refreshed on demand when stale.
* a past time: the archived snapshot nearest before it (backtesting against what people saw then).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.db.base import utcnow
from app.db.session import session_scope
from app.models import CulturalMoment, DataSource, RegionSnapshot, Signal
from app.services.llm import BaseLLM, Usage
from app.services.population.regions import CONTEXT_CODES, EMIRATE_CONTEXT, region

from .runner import run_connector
from .safety import clean_snapshot, safe_title
from .tone import select_tone

log = logging.getLogger("kruvim.datapool")
ON_DEMAND = ["open_meteo", "google_news", "publisher_rss", "wikipedia", "calendar", "regional_trends"]


def licensed(query):
    if settings.env == "production":
        query = query.join(DataSource, Signal.source_id == DataSource.id).where(
            or_(and_(DataSource.status == "active", DataSource.licence_approved.is_(True), DataSource.reliability > 0), DataSource.status == "placeholder"))
    return query


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def hour_bucket(dt: datetime) -> datetime:
    dt = _aware(dt)
    return dt.replace(minute=0, second=0, microsecond=0)


async def _latest(s, region_code: str, kinds: list[str], since: datetime, limit: int, scope_global=False):
    regs = [region_code, "*"] if scope_global else [region_code]
    q = (select(Signal).where(and_(Signal.org_id.is_(None), Signal.region.in_(regs), Signal.kind.in_(kinds), Signal.fetched_at >= since, Signal.fetched_at <= utcnow()))
         .order_by(desc(Signal.fetched_at), desc(Signal.value)).limit(limit))
    return [x for x in (await s.execute(licensed(q))).scalars().all() if safe_title(x.title)]


async def build_snapshot_data(code: str, at: datetime) -> dict:
    from app.services.datapool.retrieval import embed
    async with session_scope() as s:
        from app.services.sources import ensure_sources, signal_source
        await ensure_sources(s)
        registered = {row.id: signal_source(row) for row in (await s.execute(select(DataSource))).scalars()}
        w = await _latest(s, code, ["weather"], at - timedelta(hours=3), 1)
        tone = await select_tone(s, code, at)
        news = await _latest(s, code, ["headline"], at - timedelta(hours=24), 12)
        trends = await _latest(s, code, ["trend"], at - timedelta(hours=48), 10)
        social = await _latest(s, code, ["social_trend"], at - timedelta(hours=24), 12)
        events = await _latest(s, code, ["event"], at - timedelta(hours=36), 5)
        econ = await _latest(s, code, ["economy"], at - timedelta(hours=36), 2)
        prepared = (await s.execute(licensed(select(Signal).where(Signal.org_id.is_(None), Signal.region.in_([code, "*"]), Signal.fetched_at <= at,
            Signal.observed_at <= at, Signal.fetched_at >= at - timedelta(days=2)).order_by(Signal.fetched_at.desc()).limit(200)))).scalars().all()
        prepared = [x for x in prepared if safe_title(x.title) and (x.kind != "social_trend" or x.region == code)]
        moment = (await s.execute(select(CulturalMoment).where(CulturalMoment.region == code,
            CulturalMoment.day == at.replace(hour=0, minute=0, second=0, microsecond=0)))).scalar_one_or_none()
        series = (await s.execute(licensed(select(Signal).where(Signal.org_id.is_(None), Signal.region.in_([code, "*"]),
            Signal.kind.in_(["trend", "social_trend"]), Signal.value.is_not(None), Signal.observed_at <= at,
            Signal.observed_at >= at - timedelta(days=30)).order_by(Signal.observed_at.desc()).limit(500)))).scalars().all()
    def metadata(item):
        provenance = registered.get(item.source_id, {"status": "placeholder", "label": "estimate, source pending", "source_weight": 0})
        return {"id": item.id, "source": item.source, "source_id": item.source_id, "region": item.region, "language": item.lang,
                "nationality_groups": item.payload.get("nationality_groups", []), "calendar_membership": item.payload.get("calendar_membership"),
                "provenance": provenance, "source_weight": provenance["source_weight"]}
    freshness = {}
    for item in prepared:
        if item.kind == "tone":
            continue
        age = max(0, (at - _aware(item.observed_at)).total_seconds() / 3600)
        maximum = settings.signal_max_age_hours.get(item.kind, 6)
        key = item.source
        if key not in freshness or age < freshness[key]["age_hours"]:
            freshness[key] = {"source": key, "region": code, "age_hours": round(age, 1), "max_age_hours": maximum, "stale": age > maximum}
    for source, kind in (("open_meteo", "weather"), ("google_news", "headline"), ("wikipedia", "trend"), ("calendar", "event"), ("gdelt", "tone")):
        if source not in freshness:
            freshness[source] = {"source": source, "region": code, "age_hours": None,
                                 "max_age_hours": settings.signal_max_age_hours.get(kind, 6), "stale": True, "status": "source_unavailable"}
    reg = region(code)
    local = at + timedelta(hours=reg["tz_offset"])
    data = {
        "region": code, "name": reg["name"], "city": reg["city"], "at": at.isoformat(),
        "local_time": local.strftime("%a %H:%M"), "local_hour": local.hour,
        "weather": {**w[0].payload, **metadata(w[0])} if w else None,
        "tone": tone,
        "news": [{"title": x.title, "url": x.url, **metadata(x)} for x in news],
        "trending": [{"title": x.title, "views": x.value, "at": x.observed_at.isoformat(), **metadata(x)} for x in trends],
        "social": [{"title": x.title, "platform": x.payload.get("platform"), "value": x.value, "url": x.url, "at": x.observed_at.isoformat(), **metadata(x)} for x in social],
        "events": sorted([{"name": x.title, **x.payload, **metadata(x)} for x in events], key=lambda e: e.get("days_away") if e.get("days_away") is not None else 999),
        "economy": [{"title": x.title, "value": x.value, **metadata(x)} for x in econ],
        "source_weights": {x.source: registered.get(x.source_id, {}).get("source_weight", 0) for x in prepared},
        "signals": [{**metadata(x), "kind": x.kind, "title": x.title,
                     "value": x.value,
                     "embedding": embed(x.title + " " + str(x.payload.get("summary", ""))).tolist(),
                     "summary": str(x.payload.get("summary", ""))[:500], "at": x.observed_at.isoformat(), "url": x.url} for x in prepared],
        "freshness": list(freshness.values()), "stale_sources": [x for x in freshness.values() if x["stale"]],
        "cultural_moment": moment.note if moment and safe_title(moment.note) else "Topics on people's minds: " + "; ".join(x.title for x in news[:3]),
        "cultural_moment_by": moment.model if moment else "template",
        "trend_series": [{"title": x.title, "source": x.source, "value": x.value, "at": x.observed_at.isoformat()} for x in series],
    }
    apply_tone(data, tone)
    return data


def apply_tone(data, tone):
    from .retrieval import embed
    data["tone"] = tone
    data["signals"] = [x for x in data.get("signals", []) if x.get("kind") != "tone"]
    freshness = [x for x in data.get("freshness", []) if x["source"] not in ("gdelt", "headline_tone")]
    if tone:
        source = tone["tone_source"]
        weight = tone["source_weight"] * tone.get("provenance", {}).get("source_weight", 0)
        data.setdefault("source_weights", {})[source] = weight
        title = f"News tone {tone['avg']:+.1f} · {tone['source_label']}"
        data["signals"].append({"id": tone["signal_id"], "source": source, "kind": "tone", "title": title,
                                "value": tone["avg"], "source_weight": weight, "at": tone["observed_at"], "region": data["region"],
                                "provenance": tone.get("provenance"), "source_id": tone.get("source_id"),
                                "summary": tone.get("warning") or "Regional article tone", "embedding": embed(title).tolist()})
        freshness.append({"source": "gdelt", "region": data["region"], "age_hours": tone["age_hours"],
                          "stale": bool(tone.get("warning")), "status": "fallback" if tone.get("warning") else "ok",
                          "note": tone.get("warning"), "tone_source": source})
    else:
        freshness.append({"source": "gdelt", "region": data["region"], "age_hours": None, "stale": True,
                          "status": "source_unavailable", "note": "News tone source unavailable: no GDELT, regional headlines or previous value"})
    data["freshness"] = freshness
    data["stale_sources"] = [x for x in freshness if x["stale"]]


def template_brief(d: dict) -> str:
    parts = [f"{d['city']}, {d['local_time']} local time."]
    w = d.get("weather")
    if w:
        parts.append(f"{w['temp_c']:.0f}°C (feels {w['feels_c']:.0f}°C), {w['text']}.")
    t = d.get("tone")
    if t and t.get("avg") is not None:
        mood = "sharply negative" if t["avg"] < -4 else "negative" if t["avg"] < -2 else "mixed" if t["avg"] < 0.5 else "positive"
        parts.append(f"Local news tone is {mood} ({t['avg']:+.1f}; {t.get('source_label', 'GDELT')})." +
                     (" Treat this lower-confidence estimate cautiously." if t.get("source_weight", 1) < 1 else ""))
    if d.get("news"):
        parts.append("Top stories: " + "; ".join(n["title"] for n in d["news"][:3]) + ".")
    if d.get("trending"):
        parts.append("Most read: " + ", ".join(x["title"] for x in d["trending"][:4]) + ".")
    if d.get("events"):
        e = d["events"][0]
        parts.append(e['name'] + "." if e.get("days_away") is None else f"Coming up: {e['name']} in {e['days_away']} days.")
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
        tasks = [asyncio.create_task(run_connector(key, missing)) for key in ON_DEMAND]
        try:
            _, pending = await asyncio.wait(tasks, timeout=20)
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()


def aggregate_uae(country: dict, emirates: dict[str, dict]) -> dict:
    """A union of dated evidence, never an invented national average of emirate measurements."""
    out = {**country, "city": "UAE · all emirates", "weather": None,
           "weather_by_emirate": {code: data.get("weather") for code, data in emirates.items()},
           "tone_by_emirate": {code: data.get("tone") for code, data in emirates.items()},
           "emirates": list(emirates), "brief_by": "template"}
    for key in ("signals", "news", "trending", "social", "events", "economy", "trend_series", "freshness", "stale_sources"):
        unique = {}
        for data in [country, *emirates.values()]:
            for item in data.get(key, []):
                identity = (item.get("id"), item.get("region"), item.get("source"), item.get("title", item.get("name")), item.get("at"))
                unique.setdefault(identity, item)
        out[key] = list(unique.values())
    out["source_weights"] = {key: weight for data in [country, *emirates.values()] for key, weight in data.get("source_weights", {}).items()}
    out["brief"] = " ".join(f"{data['city']}: {data.get('brief', 'Source unavailable')}" for data in emirates.values())
    return out


def weighted_context(snapshots):
    """The discovery UI may preview pending sources; prediction and graph prompts may not weight them."""
    out, checks = {}, {}
    for code, snapshot in snapshots.items():
        data = dict(snapshot)
        for key in ("signals", "news", "trending", "social", "events", "economy", "trend_series"):
            data[key] = []
            for item in snapshot.get(key, []):
                provenance = item.get("provenance") or {"status": "placeholder", "label": "estimate, source pending", "source_weight": 0}
                checks[provenance.get("source_id", item.get("source", "pending"))] = provenance
                if item.get("source_weight", 0) > 0 and provenance.get("production_eligible"):
                    data[key].append(item)
        weather = snapshot.get("weather")
        if weather:
            metadata = weather.get("provenance") or {}
            checks[metadata.get("source_id", "open_meteo")] = metadata
            if not metadata.get("production_eligible"):
                data["weather"] = None
        tone = snapshot.get("tone")
        if tone and snapshot.get("source_weights", {}).get(tone["tone_source"], 0) <= 0:
            data["tone"] = None
        data["cultural_moment"] = "Topics in licensed regional headlines: " + "; ".join(item["title"] for item in data["news"][:3])
        if "local_time" in data:
            data["brief"], data["brief_by"] = template_brief(data), "template"
        out[code] = data
    if "AE" in out and all(code in out for code in EMIRATE_CONTEXT_CODES):
        out["AE"] = aggregate_uae(out["AE"], {code: out[code] for code in EMIRATE_CONTEXT_CODES})
    return out, list(checks.values())


EMIRATE_CONTEXT_CODES = [r["code"] for r in EMIRATE_CONTEXT]


async def snapshots_at(codes: list[str], at: datetime | None, llm: BaseLLM | None = None, usage: Usage | None = None,
                       org_id: str | None = None, with_briefs: bool = True) -> dict[str, dict]:
    expanded = list(dict.fromkeys([*codes, *([r["code"] for r in EMIRATE_CONTEXT] if "AE" in codes else [])]))
    out = await _snapshots_at(expanded, at, llm, usage, org_id, with_briefs)
    # Hourly caching and archive replay must never preserve a revoked production entitlement.
    async with session_scope() as s:
        from app.services.sources import ensure_sources, signal_source
        await ensure_sources(s)
        sources = {row.key: signal_source(row) for row in (await s.execute(select(DataSource))).scalars()}
    for data in out.values():
        weights = {}
        for key in ("signals", "news", "trending", "social", "events", "economy", "trend_series"):
            items = []
            for item in data.get(key, []):
                source = item.get("source")
                metadata = sources.get(source, sources["placeholder_priors"])
                if item.get("kind") == "tone" and any(not sources.get(k, {}).get("production_eligible") for k in (data.get("tone") or {}).get("upstream_sources", [])):
                    metadata = {**metadata, "production_eligible": False, "source_weight": 0, "label": "Upstream headline reuse approval pending"}
                if settings.env == "production" and not metadata["production_eligible"] and metadata["status"] != "placeholder":
                    continue
                weight = metadata["source_weight"]
                if item.get("kind") == "tone":
                    weight *= (data.get("tone") or {}).get("source_weight", 0)
                items.append({**item, "provenance": metadata, "source_id": metadata["source_id"], "source_weight": weight})
                weights[source] = weight
            data[key] = items
        data["source_weights"] = weights
        if data.get("weather"):
            data["weather"] = {**data["weather"], "provenance": sources["open_meteo"], "source_weight": sources["open_meteo"]["source_weight"]}
        if settings.env == "production":
            if data.get("weather") and not sources["open_meteo"]["production_eligible"]:
                data["weather"] = None
            if data.get("tone") and (not sources.get(data["tone"]["tone_source"], {}).get("production_eligible") or
                any(not sources.get(k, {}).get("production_eligible") for k in data["tone"].get("upstream_sources", []))):
                data["tone"] = None
                data["signals"] = [item for item in data["signals"] if item.get("kind") != "tone"]
            if "local_time" in data:
                data["brief"], data["brief_by"] = template_brief(data), "template"
    if "AE" in codes:
        out["AE"] = aggregate_uae(out["AE"], {r["code"]: out[r["code"]] for r in EMIRATE_CONTEXT})
        if not out["AE"].get("archived") and not out["AE"].get("archive_missing") and org_id is None:
            async with session_scope() as s:
                row = (await s.execute(select(RegionSnapshot).where(RegionSnapshot.region == "AE", RegionSnapshot.hour == hour_bucket(utcnow())))).scalar_one_or_none()
                if row:
                    row.data, row.brief, row.brief_by = out["AE"], out["AE"]["brief"], "template"
    return out


async def _snapshots_at(codes: list[str], at: datetime | None, llm: BaseLLM | None = None, usage: Usage | None = None,
                       org_id: str | None = None, with_briefs: bool = True) -> dict[str, dict]:
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
                    from .archive import load
                    try:
                        data = await load(row)
                    except Exception:
                        data = {"signals": [], "archive_unavailable": True, "stale_sources": [{"source": "archive", "region": c,
                            "age_hours": None, "stale": True}]}
                    out[c] = {**clean_snapshot(data), "brief": row.brief if safe_title(row.brief) else "Historical brief filtered for discovery safety.", "brief_by": row.brief_by, "archived": True}
        missing = [c for c in codes if c not in out]
        for c in missing:
            reg = region(c)
            out[c] = {"region": c, "name": reg["name"], "city": reg["city"], "at": at.isoformat(), "archived": False,
                      "brief": "No archived context exists for this historical moment.", "signals": [],
                      "stale_sources": [{"source": "archive", "region": c, "age_hours": None, "stale": True}],
                      "archive_missing": True}
        return out
    await ensure_fresh(codes)
    bucket = hour_bucket(now)
    need_brief = []
    async with session_scope() as s:
        for c in codes:
            row = (await s.execute(select(RegionSnapshot).where(and_(RegionSnapshot.region == c, RegionSnapshot.hour == bucket)))).scalar_one_or_none()
            if row is None:
                data = await build_snapshot_data(c, now)
                row = RegionSnapshot(region=c, hour=bucket, data=data, brief=template_brief(data), brief_by="template")
                try:
                    async with s.begin_nested():
                        s.add(row)
                        await s.flush()
                except IntegrityError:
                    row = (await s.execute(select(RegionSnapshot).where(
                        RegionSnapshot.region == c, RegionSnapshot.hour == bucket))).scalar_one()
            out[c] = {**clean_snapshot(row.data), "brief": row.brief if safe_title(row.brief) else template_brief(clean_snapshot(row.data)), "brief_by": row.brief_by, "archived": False}
            if row.brief_by == "template":
                need_brief.append(c)
    if org_id:
        # Workspace model estimates never enter the shared hourly archive.
        async with session_scope() as s:
            for code, data in out.items():
                tone = await select_tone(s, code, now, org_id, llm, usage)
                apply_tone(data, tone)
                data["brief"] = template_brief(data)
                data["brief_by"] = "template"
                if code not in need_brief:
                    need_brief.append(code)
    if at > now + timedelta(hours=1):   # scheduled publish time: same live context, shifted clock + calendar
        for c in codes:
            reg = region(c)
            local = at + timedelta(hours=reg["tz_offset"])
            out[c]["scheduled_local_time"] = local.strftime("%a %d %b %H:%M")
            out[c]["brief"] += f" (Content will be published {local.strftime('%a %H:%M')} local time.)"
    if with_briefs and need_brief and llm is not None and not llm.is_dry:
        await _llm_briefs(out, need_brief, llm, usage or Usage(), bucket, persist=org_id is None)
    return out


async def _llm_briefs(out: dict, codes: list[str], llm: BaseLLM, usage: Usage, bucket: datetime, persist=True) -> None:
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
                if row and persist:
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
    seen = set()
    for code, s in snaps.items():
        items = [("news", n["title"]) for n in s.get("news", [])] + [("trending", t["title"]) for t in s.get("trending", [])] \
            + [("social", t["title"]) for t in s.get("social", [])]
        for kind, title in items:
            if (kind, title) in seen:
                continue
            seen.add((kind, title))
            ov = ct & tokens(title)
            if ov:
                matches.append({"region": code, "kind": kind, "title": title, "overlap": sorted(ov)[:6], "strength": len(ov)})
    matches.sort(key=lambda m: -m["strength"])
    for match in matches:
        snapshot = snaps.get(match["region"], {})
        history = [x for x in snapshot.get("trend_series", []) if x["title"] == match["title"]]
        history.sort(key=lambda x: x["at"])
        # Compare only measurements from the same source, with distinct observation dates.
        if history:
            source = history[-1]["source"]
            history = list({x["at"]: x for x in history if x["source"] == source}.values())
        match["evidence"] = history[-5:]
        match["at"] = history[-1]["at"] if history else None
        match["phase"] = trend_phase(history)
        match["at"] = history[-1]["at"] if history else snapshot.get("at")
    strength = sum(min(m["strength"], 3) for m in matches[:8])
    return {"score": round(min(1.0, strength / 10), 3), "matches": matches[:12],
            "recommendation": "Refresh the angle for declining trends; use rising trends while relevant. An unknown phase needs more dated observations.",
            "method": "keyword overlap between the content and live headlines, most-read pages and social trends"}


def trend_phase(history):
    if len(history) < 3:
        return "unknown"
    values = [float(x["value"]) for x in history]
    if values[-1] < max(values) * .8:
        return "past its peak"
    if values[-1] > max(values[-2], 1) * 1.1:
        return "rising"
    return "peaking"


def all_codes() -> list[str]:
    return list(CONTEXT_CODES)
