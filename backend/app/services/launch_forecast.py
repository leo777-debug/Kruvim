"""Launch forecasts: lock a simulated prediction for a product announcement, then score it against real post-release reaction.

The locked prediction is hashed (SHA-256 over canonical JSON) so it provably predates the outcome. The outcome rates real
YouTube comments and Reddit threads on the simulation's 0-10 opinion scale with a fixed prompt; dry run uses a labelled,
deterministic lexicon stand-in. Launches announced on or before the model's training cutoff never count toward the record:
the model may already know how they were received."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, date, datetime, time, timedelta

import httpx
import numpy as np
from sqlalchemy import or_, select

from app.db.base import utcnow
from app.db.session import session_scope
from app.models import Connector, LaunchForecast, Simulation

log = logging.getLogger("kruvim.launch")

POSITIVE, NEGATIVE = 6.5, 4.0          # the simulation's own positive / negative thresholds
DIRECTION_DEADBAND = 0.2               # score changes smaller than this count as "flat"
RATE_BATCH, RATE_CAP = 25, 300
RATER_VERSION = "launch-rater-v1"
RATER_SYSTEM = (
    "You rate real public comments about a product launch on the same 0-10 opinion scale a synthetic audience uses: "
    "0 = strongly negative about the product, 5 = neutral, mixed or not about the product, 10 = strongly positive. "
    "Rate the writer's opinion of the product itself, not of other commenters, the company's past products or the video. "
    "Read sarcasm by its intended meaning. Reply with JSON only: {\"scores\": [{\"i\": <comment index>, \"score\": <number 0-10>}]} "
    "with one entry for every comment.")

_POS = {"love", "great", "amazing", "awesome", "excellent", "best", "beautiful", "impressive", "upgrade", "finally", "fantastic",
        "perfect", "good", "nice", "want", "buying", "bought", "preorder", "pre-ordered", "worth", "incredible", "smooth", "fast"}
_NEG = {"hate", "boring", "same", "overpriced", "expensive", "worst", "bad", "disappointing", "disappointed", "skip", "meh",
        "nothing", "useless", "ugly", "slow", "scam", "lazy", "copy", "regret", "worse", "pass", "gimmick", "broken"}
_WORD = re.compile(r"[\w'-]+")


def cutoff_for(announcement: date) -> datetime:
    return datetime.combine(announcement, time.min, tzinfo=UTC)


def context_time(sim: Simulation) -> datetime:
    """The moment the simulation's context was taken from: its publish time (archived snapshot before it) or, when it
    ran on live context, when it started."""
    at = sim.publish_at or sim.started_at or sim.created_at
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def snapshot_prediction(sim: Simulation) -> dict:
    r = sim.results or {}
    score = r.get("score") or {}
    objections = ((r.get("psychology") or {}).get("objections") or [])[:5]
    provider = r.get("provider") or {}
    return {
        "score": score.get("mean"), "low": score.get("low"), "high": score.get("high"),
        "positive_share": score.get("positive"), "negative_share": score.get("negative"),
        "top_objections": [{"objection": o.get("objection", ""), "n": o.get("n", 0)} for o in objections],
        "segments": [{k: seg.get(k) for k in ("name", "description", "n", "share_of_audience", "score", "low", "high", "objection")}
                     for seg in r.get("described_segments") or []],
        "simulation": {"id": sim.id, "name": sim.name, "finished_at": sim.finished_at.isoformat() if sim.finished_at else None,
                       "context_at": context_time(sim).isoformat()},
        "provider": {k: provider.get(k) for k in ("name", "preset", "dry", "voice_model", "report_model")},
        "scale": f"0-10 opinion; positive >= {POSITIVE}, negative < {NEGATIVE}",
    }


def locked_payload(f: LaunchForecast) -> dict:
    return {"company": f.company, "product": f.product, "announcement_date": f.announcement_date.isoformat(),
            "release_date": f.release_date.isoformat(), "context_cutoff": f.context_cutoff.astimezone(UTC).isoformat(),
            "model_knowledge_cutoff": f.model_knowledge_cutoff.isoformat() if f.model_knowledge_cutoff else None,
            "simulation_id": f.simulation_id, "locked_at": f.locked_at.astimezone(UTC).isoformat() if f.locked_at else None,
            "prediction": f.prediction}


def canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest(f: LaunchForecast) -> str:
    return hashlib.sha256(canonical(locked_payload(f)).encode()).hexdigest()


def status(f: LaunchForecast) -> str:
    has_outcome = (f.outcome or {}).get("score") is not None
    if f.locked_at:
        return "scored" if has_outcome else "locked"
    if has_outcome and not f.simulation_id:
        return "reference"    # an outcome-only baseline, e.g. last year's launch
    return "pending"


def eligibility(f: LaunchForecast) -> list[str]:
    """Why a forecast does not count toward the public accuracy record (empty = it counts)."""
    reasons = []
    if not f.locked_at:
        reasons.append("Not locked")
    elif f.locked_at.astimezone(UTC).date() >= f.release_date:
        reasons.append("Locked on or after release")
    if (f.prediction or {}).get("provider", {}).get("dry"):
        reasons.append("Dry-run prediction")
    if ((f.outcome or {}).get("method") or {}).get("dry"):
        reasons.append("Outcome rated by the dry-run stand-in")
    if f.model_knowledge_cutoff is None:
        reasons.append("Model training cutoff not recorded")
    elif f.announcement_date <= f.model_knowledge_cutoff:
        reasons.append(f"Announced on or before the model's training cutoff ({f.model_knowledge_cutoff.isoformat()}): "
                       "the model may already know how it was received")
    return reasons


def _direction(delta: float) -> str:
    return "up" if delta > DIRECTION_DEADBAND else "down" if delta < -DIRECTION_DEADBAND else "flat"


def compare(f: LaunchForecast, previous: LaunchForecast | None) -> dict | None:
    p, o = f.prediction or {}, f.outcome or {}
    if p.get("score") is None or o.get("score") is None:
        return None
    out = {"abs_error": round(abs(p["score"] - o["score"]), 2), "error": round(p["score"] - o["score"], 2), "direction": None}
    if p.get("positive_share") is not None and o.get("positive_share") is not None:
        out["positive_share_error"] = round(abs(p["positive_share"] - o["positive_share"]), 3)
    prev_actual = (previous.outcome or {}).get("score") if previous else None
    if prev_actual is not None:
        prev_pred = (previous.prediction or {}).get("score")
        # Compare like with like where possible: the simulation's change against its own previous prediction.
        if prev_pred is not None:
            predicted, basis = p["score"] - prev_pred, "prediction vs previous launch's prediction"
        else:
            predicted, basis = p["score"] - prev_actual, "prediction vs previous launch's actual score"
        actual = o["score"] - prev_actual
        out["direction"] = {"previous_id": previous.id, "previous_product": previous.product, "predicted": _direction(predicted),
                            "actual": _direction(actual), "correct": _direction(predicted) == _direction(actual), "basis": basis,
                            "deadband": DIRECTION_DEADBAND}
    return out


def previous_of(f: LaunchForecast, rows: list[LaunchForecast]) -> LaunchForecast | None:
    """The explicitly linked previous launch, else the company's latest earlier launch with a measured outcome."""
    if f.previous_id:
        return next((r for r in rows if r.id == f.previous_id), None)
    earlier = [r for r in rows if r.id != f.id and r.company.casefold() == f.company.casefold() and r.release_date < f.release_date
               and (r.outcome or {}).get("score") is not None]
    return max(earlier, key=lambda r: r.release_date, default=None)


# ---- collection -------------------------------------------------------------------------------------------------
async def _connector(org_id: str, key: str):
    from app.services.datapool.runner import secrets_of
    async with session_scope() as s:
        rows = (await s.execute(select(Connector).where(Connector.key == key, or_(Connector.org_id.is_(None), Connector.org_id == org_id)))).scalars().all()
    row = next((r for r in rows if r.org_id == org_id), None) or next((r for r in rows if r.org_id is None), None)
    if row is not None and not row.enabled:
        return None
    return secrets_of(row), dict(row.config) if row else {}


def _comment(item, platform: str) -> dict:
    return {"platform": platform, "text": item.title, "at": item.observed_at.isoformat() if item.observed_at else None,
            "likes": item.value or 0, "url": item.url}


async def fetch_youtube(org_id: str, video_ids: list[str], after: datetime | None, before: datetime | None, limit: int) -> list[dict]:
    from app.services.datapool.base import UA
    from app.services.datapool.connectors import REGISTRY
    if not video_ids:
        return []
    conn = await _connector(org_id, "youtube")
    if conn is None:
        return []
    secrets, _ = conn
    out = []
    async with httpx.AsyncClient(headers=UA, timeout=15) as client:
        for vid in video_ids:
            try:
                items = await REGISTRY["youtube"].comments(client, vid, secrets, limit=max(1, limit // len(video_ids)), after=after, before=before)
            except Exception as exc:
                log.info("youtube comments for %s failed: %s", vid, exc)
                continue
            out += [_comment(i, "youtube") for i in items]
    return out


async def fetch_reddit(org_id: str, query: str, after: datetime | None, before: datetime | None, limit: int) -> list[dict]:
    from app.services.datapool.base import UA
    from app.services.datapool.connectors import REGISTRY
    if not query:
        return []
    conn = await _connector(org_id, "reddit")
    if conn is None:
        return []
    secrets, config = conn
    try:
        async with httpx.AsyncClient(headers=UA, timeout=15) as client:
            items = await REGISTRY["reddit"].search(client, query, [], secrets, config, limit=min(100, limit))
    except Exception as exc:
        log.info("reddit search for %r failed: %s", query, exc)
        return []
    out = []
    for i in items:
        at = i.observed_at.astimezone(UTC) if i.observed_at else None
        if at is None or (after and at < after) or (before and at >= before):
            continue
        body = (i.payload.get("selftext") or "").strip()
        out.append({**_comment(i, "reddit"), "text": f"{i.title}\n{body}".strip()})
    return out


async def gather(org_id: str, sources: dict, after: datetime | None, before: datetime | None, limit: int = RATE_CAP) -> list[dict]:
    yt = await fetch_youtube(org_id, sources.get("youtube_video_ids") or [], after, before, limit)
    rd = await fetch_reddit(org_id, sources.get("reddit_query") or "", after, before, limit)
    seen, out = set(), []
    for c in yt + rd:
        key = c["text"].casefold().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(c)
    return out


# ---- rating -----------------------------------------------------------------------------------------------------
def dry_score(text: str) -> float:
    words = [w.casefold() for w in _WORD.findall(text)]
    pos, neg = sum(w in _POS for w in words), sum(w in _NEG for w in words)
    return float(np.clip(5 + 1.5 * (pos - neg), 0, 10))


async def rate(org_id: str, product: str, comments: list[dict]) -> tuple[list[float | None], dict]:
    from app.services import metering
    from app.services.llm import LLMError, Usage, make_llm
    from app.services.providers import resolve
    async with session_scope() as s:
        res = await resolve(s, org_id)
    llm = make_llm(res.settings)
    try:
        if llm.is_dry:
            return [dry_score(c["text"]) for c in comments], {"rater": "dry-run lexicon stand-in (not a model)", "dry": True,
                                                               "version": RATER_VERSION}
        usage = Usage()
        scores: list[float | None] = [None] * len(comments)
        for start in range(0, len(comments), RATE_BATCH):
            batch = comments[start:start + RATE_BATCH]
            listing = "\n".join(f"[{k}] {c['text'][:600]}" for k, c in enumerate(batch))
            try:
                reply = await llm.complete_json(system=RATER_SYSTEM, user=f"Product: {product}\n\nComments:\n{listing}", role="extract",
                                                max_tokens=60 + 20 * len(batch), usage=usage, temperature=0)
            except LLMError as exc:
                log.info("launch rater batch failed: %s", exc)
                continue
            for row in reply.get("scores") or []:
                try:
                    k, v = int(row["i"]), float(row["score"])
                except (KeyError, TypeError, ValueError):
                    continue
                if 0 <= k < len(batch):
                    scores[start + k] = float(np.clip(v, 0, 10))
        await metering.record(org_id, None, "launch_rating", usage, res)
        return scores, {"rater": f"{res.settings.provider}:{llm.model_for('extract')}", "dry": False, "version": RATER_VERSION,
                        "temperature": 0, "batch": RATE_BATCH}
    finally:
        await llm.aclose()


def summarise(comments: list[dict], scores: list[float | None]) -> dict:
    rated = [(c, sc) for c, sc in zip(comments, scores) if sc is not None]
    if not rated:
        return {"score": None, "n": 0}
    values = np.array([sc for _, sc in rated])
    by_platform = {}
    for platform in sorted({c["platform"] for c, _ in rated}):
        v = np.array([sc for c, sc in rated if c["platform"] == platform])
        by_platform[platform] = {"n": int(v.size), "score": round(float(v.mean()), 2)}
    order = np.argsort(values)

    def pick(idx):
        return [{"text": rated[i][0]["text"][:280], "score": round(float(values[i]), 1), "url": rated[i][0]["url"],
                 "platform": rated[i][0]["platform"]} for i in idx]
    return {"score": round(float(values.mean()), 2), "positive_share": round(float((values >= POSITIVE).mean()), 3),
            "negative_share": round(float((values < NEGATIVE).mean()), 3), "n": int(values.size), "by_platform": by_platform,
            "examples": {"most_negative": pick(order[:3]), "most_positive": pick(order[::-1][:3])}}


async def collect_outcome(f: LaunchForecast) -> dict:
    window = int((f.sources or {}).get("window_days") or 14)
    after = datetime.combine(f.release_date, time.min, tzinfo=UTC)
    before = min(utcnow(), after + timedelta(days=window))
    comments = await gather(f.org_id, f.sources or {}, after, before)
    sample = comments[:RATE_CAP]
    scores, method = await rate(f.org_id, f"{f.company} {f.product}", sample)
    result = summarise(sample, scores)
    method.update(scale=f"0-10 opinion; positive >= {POSITIVE}, negative < {NEGATIVE}", aggregate="unweighted mean of rated comments",
                  sources=sorted({c["platform"] for c in sample}), youtube_video_ids=(f.sources or {}).get("youtube_video_ids") or [],
                  reddit_query=(f.sources or {}).get("reddit_query") or "")
    return {**result, "collected": len(comments), "method": method, "window": {"from": after.isoformat(), "to": before.isoformat(),
            "days": window, "complete": before >= after + timedelta(days=window)}, "collected_at": utcnow().isoformat(),
            "attempts": int((f.outcome or {}).get("attempts") or 0) + 1}


async def collect_background(f: LaunchForecast, limit: int = 60) -> dict:
    """Pre-announcement comments (e.g. on the previous launch's videos) as seed material. Nothing dated at or after the
    forecast's context cutoff is kept."""
    src = f.sources or {}
    items = await gather(f.org_id, {"youtube_video_ids": src.get("background_video_ids") or [], "reddit_query": src.get("background_reddit_query") or ""},
                         None, f.context_cutoff, limit)
    items = [c for c in items if c["at"] and datetime.fromisoformat(c["at"]) < f.context_cutoff][:limit]
    lines = [f"Background: public reaction to earlier launches, all dated before {f.context_cutoff.date().isoformat()}."]
    lines += [f"- [{c['platform']} {c['at'][:10]}] {c['text'][:400]}" for c in items]
    return {"items": items, "n": len(items), "cutoff": f.context_cutoff.isoformat(), "collected_at": utcnow().isoformat(),
            "seed_text": "\n".join(lines)}
