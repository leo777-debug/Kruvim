"""Prediction track record: hash-chained ledger, locking, honest scoring against baselines, public scoreboard."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from tests.test_e2e_dry import SCRIPT, wait_for


async def _completed_sim(client, h, live=True):
    """A completed dry-run simulation; `live` relabels it as a real-model run so it can count toward the record."""
    pr = (await client.post("/projects", json={"name": "Forecasts"}, headers=h)).json()
    body = {"name": "Launch reaction", "requirement": "How will people react to this launch?",
            "content": {"type": "video", "title": "Launch", "platform": "tiktok", "transcript": SCRIPT}, "audience": {"regions": ["AE"]},
            "overrides": {"voice": 10, "crowd": 500, "stakeholders": 1, "hours": 2, "minutes_per_round": 60, "listening": False}}
    sid = (await client.post(f"/projects/{pr['id']}/simulations", json=body, headers=h)).json()["id"]
    for step, field, want in (("graph", "status", "graph_ready"), ("environment", "status", "ready"), ("start", "status", "completed")):
        await client.post(f"/simulations/{sid}/{step}", headers=h)
        await wait_for(client, h, sid, field, {want})
    if live:
        from app.db.session import session_scope
        from app.models import Simulation
        async with session_scope() as s:
            sim = await s.get(Simulation, sid)
            sim.results = {**sim.results, "provider": {**sim.results["provider"], "dry": False, "name": "openai", "voice_model": "m"}}
    return sid


def _forecast(sid, **kw):
    return {"question": "Will the launch land well with UAE viewers?", "domain": "launch", "country": "AE", "kind": "numeric",
            "metric": "score", "resolution_criteria": "Mean rated reaction of the first 300 public comments in the first week.",
            "resolves_on": (date.today() + timedelta(days=10)).isoformat(), "baseline_value": 5.0, "baseline_method": "neutral midpoint",
            "model_knowledge_cutoff": "2026-01-31", "simulation_id": sid, **kw}


# ---- ledger --------------------------------------------------------------------------------------------------------------
async def test_ledger_chains_every_entry_and_detects_tampering(client):
    from app.db.session import session_scope
    from app.services import track_record as tr
    async with session_scope() as s:
        for i in range(3):
            await tr.append(s, "lock", "forecast", f"f{i}", "org", tr.sha({"i": i}))
    ledger = (await client.get("/public/ledger")).json()           # public: no sign-in needed
    entries = ledger["entries"]
    assert [e["seq"] for e in entries] == [1, 2, 3] and entries[0]["prev_hash"] == tr.GENESIS
    assert tr.verify_chain(entries) == {"ok": True, "entries": 3, "head": ledger["head"]}
    assert "org" not in str(entries) and all("org_id" not in e for e in entries)

    forged = [dict(e) for e in entries]
    forged[1]["payload_hash"] = tr.sha({"i": "rewritten"})
    assert tr.verify_chain(forged) == {"ok": False, "broken_at": 2}
    dropped = [entries[0], entries[2]]
    assert not tr.verify_chain(dropped)["ok"]


# ---- maths ---------------------------------------------------------------------------------------------------------------
def test_yes_no_probability_comes_from_the_simulation_interval():
    from types import SimpleNamespace

    from app.services import track_record as tr
    sim = SimpleNamespace(id="s", name="n", finished_at=None, results={"score": {"mean": 6.0, "low": 5.0, "high": 7.0}, "provider": {"dry": False}})
    at = lambda t: tr.snapshot(SimpleNamespace(metric="score", kind="binary", threshold=t), sim)["probability"]  # noqa: E731
    assert at(6.0) == 0.5
    assert 0.97 < at(5.0) <= 0.99 and 0.01 <= at(7.0) < 0.03          # the interval edges sit near 97.5% / 2.5%
    assert at(9.5) == 0.01                                             # never claims certainty


def test_scores_are_relative_to_a_baseline_and_calibration_is_binned():
    from app.services import track_record as tr

    def rec(kind, predicted, outcome, baseline, low=None, high=None, happened=None):
        r = {"kind": kind, "predicted": predicted, "outcome": outcome, "baseline": baseline, "low": low, "high": high,
             "status": "resolved", "excluded": [], "happened": happened}
        return r | {"scores": tr.score(r)}
    numeric = [rec("numeric", 6.0, 6.5, 5.0, 5.5, 7.0), rec("numeric", 4.0, 3.0, 5.0, 3.5, 4.5)]
    s = tr.summarise(numeric)["numeric"]
    assert (s["mae"], s["baseline_mae"], s["skill"], s["interval_coverage"]) == (0.75, 1.75, 0.571, 0.5)

    binary = [rec("binary", 0.8, 1, 0.5, happened=True), rec("binary", 0.75, 1, 0.5, happened=False), rec("binary", 0.2, 0, 0.5, happened=False)]
    b = tr.summarise(binary)["binary"]
    assert b["brier"] == round((0.04 + 0.5625 + 0.04) / 3, 4) and b["baseline_brier"] == 0.25 and b["skill"] > 0
    assert [(x["range"], x["n"], x["observed"]) for x in b["calibration"]] == [("20-30%", 1, 0.0), ("70-80%", 1, 0.0), ("80-90%", 1, 1.0)]


# ---- the full life of a forecast ---------------------------------------------------------------------------------------
async def test_lock_resolve_score_and_prove(client, auth, monkeypatch):
    from app.services import track_record as tr
    h, _ = auth
    sid = await _completed_sim(client, h)
    r = await client.post("/forecasts", headers=h, json=_forecast(None))
    fid = r.json()["id"]
    assert (await client.post(f"/forecasts/{fid}/lock", headers=h)).status_code == 400          # no simulation linked
    await client.put(f"/forecasts/{fid}", headers=h, json=_forecast(sid))

    locked = await client.post(f"/forecasts/{fid}/lock", headers=h)
    assert locked.status_code == 200 and locked.json()["status"] == "locked" and locked.json()["excluded"] == []
    proof = (await client.get(f"/forecasts/{fid}/proof", headers=h)).json()
    import hashlib
    assert hashlib.sha256(proof["payload"].encode()).hexdigest() == proof["prediction_hash"]
    assert proof["ledger_entries"][0]["payload_hash"] == proof["prediction_hash"]

    # Locked forecasts can't be edited, deleted or resolved early.
    assert (await client.put(f"/forecasts/{fid}", headers=h, json=_forecast(sid, question="A different question entirely"))).status_code == 409
    assert (await client.delete(f"/forecasts/{fid}", headers=h)).status_code == 409
    outcome = {"value": 6.1, "evidence_url": "https://example.com/comments"}
    assert (await client.post(f"/forecasts/{fid}/resolve", headers=h, json=outcome)).json()["error"]["code"] == "not_due"

    monkeypatch.setattr(tr, "today", lambda: date.today() + timedelta(days=11))
    assert (await client.post(f"/forecasts/{fid}/resolve", headers=h, json={**outcome, "value": 11})).status_code == 400
    resolved = (await client.post(f"/forecasts/{fid}/resolve", headers=h, json=outcome)).json()
    assert resolved["status"] == "resolved" and resolved["scores"]["baseline_abs_error"] == pytest.approx(1.1)

    record = (await client.get("/track-record", headers=h)).json()
    assert record["summary"]["counted"] == 1 and record["summary"]["numeric"]["n"] == 1
    assert record["public_enabled"] is False
    ledger = (await client.get("/public/ledger")).json()
    assert [e["action"] for e in ledger["entries"]] == ["lock", "resolve"] and tr.verify_chain(ledger["entries"])["ok"]


async def test_what_does_not_count_is_shown_with_the_reason(client, auth, monkeypatch):
    h, _ = auth
    dry = await _completed_sim(client, h, live=False)
    f1 = (await client.post("/forecasts", headers=h, json=_forecast(dry))).json()["id"]
    await client.post(f"/forecasts/{f1}/lock", headers=h)
    live = await _completed_sim(client, h)
    f2 = (await client.post("/forecasts", headers=h, json=_forecast(live, model_knowledge_cutoff=None))).json()["id"]
    await client.post(f"/forecasts/{f2}/lock", headers=h)
    f3 = (await client.post("/forecasts", headers=h, json=_forecast(live))).json()["id"]
    await client.post(f"/forecasts/{f3}/lock", headers=h)
    assert (await client.post(f"/forecasts/{f3}/void", headers=h, json={"reason": "The question turned out to be ambiguous."})).json()["status"] == "void"

    rows = {r["id"]: r for r in (await client.get("/track-record", headers=h)).json()["records"]}
    assert rows[f1]["excluded"] == ["Dry-run prediction"]
    assert rows[f2]["excluded"] == ["Model training cutoff not recorded"]
    assert "Voided" in rows[f3]["excluded"]
    summary = (await client.get("/track-record", headers=h)).json()["summary"]
    assert summary["voided"] == 1 and summary["counted"] == 0

    late = _forecast(live, resolves_on=date.today().isoformat())
    f4 = (await client.post("/forecasts", headers=h, json=late)).json()["id"]
    assert (await client.post(f"/forecasts/{f4}/lock", headers=h)).json()["error"]["code"] == "too_late"
    bad = await client.post("/forecasts", headers=h, json=_forecast(live, kind="binary", threshold=6.5, baseline_value=6.0))
    assert bad.status_code == 422                                     # a yes/no baseline is a probability


async def test_public_scoreboard_is_off_until_enabled_and_shows_only_public_forecasts(client, auth, monkeypatch):
    from app.core.config import settings
    h, _ = auth
    assert (await client.get("/public/track-record")).status_code == 404
    sid = await _completed_sim(client, h)
    shown = (await client.post("/forecasts", headers=h, json=_forecast(sid, public=True, kind="binary", threshold=6.0,
                                                                        baseline_value=0.5))).json()["id"]
    hidden = (await client.post("/forecasts", headers=h, json=_forecast(sid))).json()["id"]
    for fid in (shown, hidden):
        assert (await client.post(f"/forecasts/{fid}/lock", headers=h)).status_code == 200
    monkeypatch.setattr(settings, "public_track_record", True)
    board = (await client.get("/public/track-record")).json()
    assert [r["id"] for r in board["records"]] == [shown]
    assert 0.01 <= board["records"][0]["predicted"] <= 0.99
    assert sid not in str(board) and "org" not in str(board["records"][0])


async def test_forecasts_are_private_to_their_workspace(client, auth):
    h, _ = auth
    sid = await _completed_sim(client, h)
    fid = (await client.post("/forecasts", headers=h, json=_forecast(sid))).json()["id"]
    other = (await client.post("/auth/register", json={"email": "rival@example.com", "password": "rival-password-1"})).json()
    oh = {"Authorization": f"Bearer {other['access_token']}"}
    for method, path in (("GET", f"/forecasts/{fid}"), ("POST", f"/forecasts/{fid}/lock"), ("GET", f"/forecasts/{fid}/proof")):
        assert (await client.request(method, path, headers=oh)).status_code == 404
    assert (await client.get("/track-record", headers=oh)).json()["records"] == []
    # Another workspace's simulation can't be used as a forecast's answer.
    assert (await client.post("/forecasts", headers=oh, json=_forecast(sid))).status_code == 404
