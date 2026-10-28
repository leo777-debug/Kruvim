"""Prediction track record: lock forecasts before their outcome, chain every lock and resolution in a public hash ledger,
and score resolved forecasts against a stated baseline so the record cannot flatter itself.

What counts toward the record (anything else is listed with the reason it does not count):
* locked before the date it resolves, from a completed simulation on a real model (never a dry run);
* resolving after the model's training cutoff, so the model cannot already know the answer;
* resolved with a measured outcome; voided forecasts stay visible and are counted separately (no silent deletions).

Scores: numeric forecasts use absolute error against the baseline's error (skill = 1 - MAE / baseline MAE) and the share of
outcomes inside the simulation's 95% interval; yes/no forecasts use the Brier score against the baseline probability and a
calibration table (when Kruvim says 70%, how often did it happen?), each with Wilson 95% intervals."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, date

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.base import utcnow
from app.models import Forecast, LaunchForecast, LedgerEntry, Simulation

GENESIS = "0" * 64
METRICS = {"score": (0.0, 10.0, "reaction score (0-10)"), "positive_share": (0.0, 1.0, "share of positive reactions")}
P_MIN, P_MAX = 0.01, 0.99


def canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha(payload: dict) -> str:
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


# ---- ledger ---------------------------------------------------------------------------------------------------------
def entry_body(e: LedgerEntry) -> dict:
    """Exactly what each entry's hash commits to (the org is kept out so the ledger can be public)."""
    return {"seq": e.seq, "created_at": e.created_at.astimezone(UTC).isoformat(), "action": e.action, "subject_type": e.subject_type,
            "subject_id": e.subject_id, "payload_hash": e.payload_hash, "prev_hash": e.prev_hash}


async def append(s: AsyncSession, action: str, subject_type: str, subject_id: str, org_id: str | None, payload_hash: str) -> LedgerEntry:
    if s.bind.dialect.name == "postgresql":
        await s.execute(text("SELECT pg_advisory_xact_lock(727274)"))   # one writer at a time keeps the chain linear
    last = (await s.execute(select(LedgerEntry).order_by(LedgerEntry.seq.desc()).limit(1))).scalar_one_or_none()
    e = LedgerEntry(seq=(last.seq + 1) if last else 1, created_at=utcnow(), action=action, subject_type=subject_type,
                    subject_id=subject_id, org_id=org_id, payload_hash=payload_hash, prev_hash=last.entry_hash if last else GENESIS)
    e.entry_hash = sha(entry_body(e))
    s.add(e)
    await s.flush()
    return e


def public_entry(e: LedgerEntry) -> dict:
    return {**entry_body(e), "entry_hash": e.entry_hash}


def verify_chain(entries: list[dict], prev: str = GENESIS) -> dict:
    """Recompute every hash; anyone can run the same check on the published ledger."""
    for e in entries:
        body = {k: e[k] for k in ("seq", "created_at", "action", "subject_type", "subject_id", "payload_hash", "prev_hash")}
        if e["prev_hash"] != prev or hashlib.sha256(canonical(body).encode()).hexdigest() != e["entry_hash"]:
            return {"ok": False, "broken_at": e["seq"]}
        prev = e["entry_hash"]
    return {"ok": True, "entries": len(entries), "head": prev}


# ---- general forecasts ------------------------------------------------------------------------------------------------
def _phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def snapshot(f: Forecast, sim: Simulation) -> dict:
    """The simulation's answer to the question, with the uncertainty it reported."""
    r = sim.results or {}
    score = r.get("score") or {}
    provider = r.get("provider") or {}
    if f.metric == "score":
        mean, low, high = score.get("mean"), score.get("low"), score.get("high")
    else:
        mean, low, high = score.get("positive"), None, None
    if mean is None:
        raise AppError("The linked simulation has no result for this measure.")
    out = {"metric": f.metric, "value": round(float(mean), 4), "low": low, "high": high,
           "simulation": {"id": sim.id, "name": sim.name, "finished_at": sim.finished_at.isoformat() if sim.finished_at else None},
           "provider": {k: provider.get(k) for k in ("name", "preset", "dry", "voice_model", "report_model")}}
    if f.kind == "binary":
        if low is None or high is None or high <= low:
            raise AppError("A yes/no forecast needs the simulation's uncertainty interval; use the reaction score.")
        sd = (high - low) / 3.92                    # the simulation reports a 95% interval
        p = 1 - _phi((f.threshold - mean) / sd)
        out["probability"] = round(min(P_MAX, max(P_MIN, p)), 4)
        out["probability_method"] = "normal approximation from the simulation's 95% interval, clipped to 1%-99%"
    return out


def locked_payload(f: Forecast) -> dict:
    return {"question": f.question, "domain": f.domain, "country": f.country, "kind": f.kind, "metric": f.metric,
            "threshold": f.threshold, "resolution_criteria": f.resolution_criteria, "resolves_on": f.resolves_on.isoformat(),
            "baseline": {"value": f.baseline_value, "method": f.baseline_method},
            "model_knowledge_cutoff": f.model_knowledge_cutoff.isoformat() if f.model_knowledge_cutoff else None,
            "simulation_id": f.simulation_id, "locked_at": f.locked_at.astimezone(UTC).isoformat() if f.locked_at else None,
            "public": f.public, "prediction": f.prediction}


def eligibility(f: Forecast) -> list[str]:
    reasons = []
    if not f.locked_at:
        reasons.append("Not locked")
    elif f.locked_at.astimezone(UTC).date() >= f.resolves_on:
        reasons.append("Locked on or after the day it resolves")
    if (f.prediction or {}).get("provider", {}).get("dry"):
        reasons.append("Dry-run prediction")
    if f.model_knowledge_cutoff is None:
        reasons.append("Model training cutoff not recorded")
    elif f.resolves_on <= f.model_knowledge_cutoff:
        reasons.append("Resolves on or before the model's training cutoff: the model may already know the answer")
    if f.status == "void":
        reasons.append("Voided")
    return reasons


def check_outcome(f: Forecast, value: float) -> float:
    low, high, label = METRICS[f.metric]
    if not low <= value <= high:
        raise AppError(f"The measured {label} must be between {low:g} and {high:g}.", code="bad_outcome")
    return float(value)


# ---- one shape for every scored record --------------------------------------------------------------------------------
def record_of_forecast(f: Forecast) -> dict:
    p, o = f.prediction or {}, f.outcome or {}
    rec = {"id": f.id, "source": "forecast", "question": f.question, "domain": f.domain, "country": f.country, "kind": f.kind,
           "metric": f.metric, "threshold": f.threshold, "resolves_on": f.resolves_on.isoformat(), "status": f.status,
           "locked_at": f.locked_at, "prediction_hash": f.prediction_hash, "public": f.public,
           "predicted": p.get("probability") if f.kind == "binary" else p.get("value"), "low": p.get("low"), "high": p.get("high"),
           "baseline": f.baseline_value, "baseline_method": f.baseline_method, "outcome": o.get("value"),
           "evidence_url": o.get("evidence_url"), "excluded": eligibility(f)}
    if f.kind == "binary" and o.get("value") is not None:
        rec["happened"] = o["value"] >= f.threshold
    return rec | {"scores": score(rec)}


def record_of_launch(f: LaunchForecast, previous: LaunchForecast | None, excluded: list[str]) -> dict:
    p, o = f.prediction or {}, f.outcome or {}
    prev_actual = (previous.outcome or {}).get("score") if previous else None
    rec = {"id": f.id, "source": "launch", "question": f"How will people react to {f.company} {f.product}?", "domain": "launch",
           "country": "GLOBAL", "kind": "numeric", "metric": "score", "threshold": None, "resolves_on": f.release_date.isoformat(),
           "status": "resolved" if o.get("score") is not None and f.locked_at else "locked" if f.locked_at else "draft",
           "locked_at": f.locked_at, "prediction_hash": f.prediction_hash, "public": False,
           "predicted": p.get("score"), "low": p.get("low"), "high": p.get("high"),
           "baseline": prev_actual if prev_actual is not None else 5.0,
           "baseline_method": f"same as {previous.product}'s measured reaction" if prev_actual is not None else "neutral midpoint (5.0)",
           "outcome": o.get("score"), "evidence_url": None, "excluded": excluded}
    return rec | {"scores": score(rec)}


def score(rec: dict) -> dict | None:
    if rec["predicted"] is None or rec["outcome"] is None or rec["status"] == "void":
        return None
    if rec["kind"] == "binary":
        o = 1.0 if rec.get("happened") else 0.0
        return {"brier": round((rec["predicted"] - o) ** 2, 4), "baseline_brier": round((rec["baseline"] - o) ** 2, 4)}
    out = {"abs_error": round(abs(rec["predicted"] - rec["outcome"]), 4), "baseline_abs_error": round(abs(rec["baseline"] - rec["outcome"]), 4)}
    if rec["low"] is not None and rec["high"] is not None:
        out["inside_interval"] = rec["low"] <= rec["outcome"] <= rec["high"]
    return out


def wilson(k: int, n: int) -> list[float] | None:
    if not n:
        return None
    p, z = k / n, 1.96
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0, centre - margin), 3), round(min(1, centre + margin), 3)]


def summarise(records: list[dict]) -> dict:
    counted = [r for r in records if not r["excluded"] and r["scores"]]
    numeric = [r for r in counted if r["kind"] == "numeric"]
    binary = [r for r in counted if r["kind"] == "binary"]
    out = {"counted": len(counted), "excluded": sum(1 for r in records if r["excluded"] and r["status"] != "void"),
           "voided": sum(1 for r in records if r["status"] == "void"), "open": sum(1 for r in records if r["status"] == "locked"),
           "numeric": None, "binary": None}
    if numeric:
        mae = sum(r["scores"]["abs_error"] for r in numeric) / len(numeric)
        base = sum(r["scores"]["baseline_abs_error"] for r in numeric) / len(numeric)
        with_interval = [r for r in numeric if "inside_interval" in r["scores"]]
        inside = sum(r["scores"]["inside_interval"] for r in with_interval)
        out["numeric"] = {"n": len(numeric), "mae": round(mae, 3), "baseline_mae": round(base, 3),
                          "skill": round(1 - mae / base, 3) if base > 0 else None,
                          "interval_coverage": round(inside / len(with_interval), 3) if with_interval else None,
                          "interval_coverage_ci": wilson(inside, len(with_interval)), "interval_target": 0.95}
    if binary:
        brier = sum(r["scores"]["brier"] for r in binary) / len(binary)
        base = sum(r["scores"]["baseline_brier"] for r in binary) / len(binary)
        bins = []
        for lo in range(0, 100, 10):
            members = [r for r in binary if lo / 100 <= r["predicted"] < (lo + 10) / 100 or (lo == 90 and r["predicted"] == 1)]
            if members:
                k = sum(1 for r in members if r["happened"])
                bins.append({"range": f"{lo}-{lo + 10}%", "n": len(members), "mean_predicted": round(sum(r["predicted"] for r in members) / len(members), 3),
                             "observed": round(k / len(members), 3), "observed_ci": wilson(k, len(members))})
        out["binary"] = {"n": len(binary), "brier": round(brier, 4), "baseline_brier": round(base, 4),
                         "skill": round(1 - brier / base, 3) if base > 0 else None, "calibration": bins}
    return out


async def workspace_records(s: AsyncSession, org_id: str) -> list[dict]:
    from app.services import launch_forecast as launches
    forecasts = (await s.execute(select(Forecast).where(Forecast.org_id == org_id).order_by(Forecast.created_at.desc()))).scalars().all()
    rows = (await s.execute(select(LaunchForecast).where(LaunchForecast.org_id == org_id))).scalars().all()
    return [record_of_forecast(f) for f in forecasts] + [
        record_of_launch(f, launches.previous_of(f, rows), launches.eligibility(f)) for f in rows if f.simulation_id]


def published(rec: dict) -> dict:
    """The public scoreboard never shows workspace names, simulations or anything not in the locked question."""
    keep = ("id", "question", "domain", "country", "kind", "metric", "threshold", "resolves_on", "status", "locked_at",
            "prediction_hash", "predicted", "low", "high", "baseline", "baseline_method", "outcome", "happened", "evidence_url",
            "excluded", "scores")
    return {k: rec.get(k) for k in keep}


def today() -> date:
    return utcnow().date()
