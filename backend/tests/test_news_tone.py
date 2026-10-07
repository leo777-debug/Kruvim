import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from app.db.base import utcnow
from app.db.session import session_scope
from app.models import Signal
from app.services.datapool.connectors.news import GdeltToneConnector, _gdelt_state
from app.services.datapool.context import apply_tone
from app.services.datapool.tone import lexicon_score, select_tone
from app.services.llm import ProviderSettings, Usage, make_llm


def test_english_arabic_lexicon_and_negation():
    assert lexicon_score(["Peace and growth", "نجاح وتعاون"]) > 0
    assert lexicon_score(["War attack crisis", "وفاة وتهديد"]) < 0
    assert lexicon_score(["Not a success", "لا نجاح"]) < 0
    assert lexicon_score(["Weather bulletin"]) == 0


async def test_gdelt_contract_rate_limit_and_recorded_failure(monkeypatch, caplog):
    monkeypatch.setitem(_gdelt_state, "blocked_until", 0)
    monkeypatch.setitem(_gdelt_state, "last", 0)
    monkeypatch.setitem(_gdelt_state, "reasons", {})
    def response(request):
        assert request.url.params["query"] == "sourcecountry:saudiarabia"
        assert request.url.params["mode"] == "tonechart"
        # Documented histogram contract; the live upstream was unavailable at fixture capture.
        return httpx.Response(200, json={"tonechart": [{"bin": -6, "count": 2}, {"bin": 3, "count": 4}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        result = await GdeltToneConnector().fetch(client, [{"code": "SA", "gdelt_country": "saudiarabia"}], {}, {})
        assert result[0].value == 0 and result[0].payload["source_weight"] == 1
    monkeypatch.setitem(_gdelt_state, "last", 0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429))) as client:
        with pytest.raises(RuntimeError, match="HTTP 429"):
            await GdeltToneConnector().fetch(client, [{"code": "SA", "gdelt_country": "saudiarabia"}], {}, {})
    assert "HTTP 429" in caplog.text
    monkeypatch.setitem(_gdelt_state, "blocked_until", 0)
    monkeypatch.setitem(_gdelt_state, "last", 0)
    def unavailable(request):
        raise httpx.ConnectTimeout("Recorded upstream connection timeout")
    async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable)) as client:
        with pytest.raises(RuntimeError, match="ConnectTimeout"):
            await GdeltToneConnector().fetch(client, [{"code": "AE", "gdelt_country": "unitedarabemirates"}], {}, {})
    assert "AE: Request failed: ConnectTimeout" in caplog.text


async def test_each_fallback_step_and_plain_warnings(client):
    at = utcnow()
    async with session_scope() as s:
        assert await select_tone(s, "TN1", at) is None
        old = Signal(region="TN1", source="gdelt", kind="tone", value=-3, title="News tone", observed_at=at - timedelta(days=2), fetched_at=at - timedelta(days=2))
        s.add(old)
        await s.flush()
        last = await select_tone(s, "TN1", at)
        assert last["avg"] == -3 and last["last_known"] and "from 2 days ago" in last["source_label"]
        fixtures = json.loads((Path(__file__).parent / "fixtures/news_tone.json").read_text(encoding="utf-8"))
        headlines = fixtures["headlines"]["SA"] + fixtures["headlines"]["AE"]
        assert headlines
        for title in headlines:
            s.add(Signal(region="TN1", source="google_news", kind="headline", title=title, observed_at=at - timedelta(minutes=5), fetched_at=at - timedelta(minutes=5)))
        await s.flush()
        fallback = await select_tone(s, "TN1", at)
        assert fallback["method"] == "lexicon" and fallback["source_weight"] < 1
        assert fallback["avg"] == lexicon_score(headlines)
        assert "estimated from headlines; GDELT unavailable" in fallback["warning"]
        data = {"region": "TN1", "signals": [], "freshness": []}
        apply_tone(data, fallback)
        assert data["source_weights"]["headline_tone"] == 0  # Pending commercial reuse approval.
        assert fallback["source_weight"] == .5  # Scoring method confidence is retained separately.
        assert data["stale_sources"][0]["note"] == fallback["warning"]
        s.add(Signal(region="TN1", source="gdelt", kind="tone", value=2, title="News tone", observed_at=at - timedelta(minutes=1), fetched_at=at - timedelta(minutes=1)))
        await s.flush()
        fresh = await select_tone(s, "TN1", at)
        assert fresh["avg"] == 2 and fresh["source_weight"] == 1 and not fresh["warning"]


async def test_connected_model_is_cached_and_workspace_scoped(client, auth):
    at = utcnow()
    _, data = auth
    org_id = data["orgs"][0]["id"]
    llm = make_llm(ProviderSettings())
    llm.is_dry = False
    llm.model_for = lambda role: "local-model"
    llm.complete_json = AsyncMock(return_value={"avg": -2.5})
    async with session_scope() as s:
        s.add(Signal(region="TN2", source="google_news", kind="headline", title="Regional peace and growth", observed_at=at, fetched_at=at))
        await s.flush()
        result = await select_tone(s, "TN2", at, org_id, llm, Usage())
        assert result["avg"] == -2.5 and result["method"] == "model" and result["source_weight"] == .7
        assert (await select_tone(s, "TN2", at, org_id, llm))["signal_id"] == result["signal_id"]
        llm.complete_json.assert_awaited_once()
        assert (await s.get(Signal, result["signal_id"])).org_id == org_id
        public = await select_tone(s, "TN2", at)
        assert public["method"] == "lexicon" and public["avg"] > 0
        llm.complete_json = AsyncMock(return_value={"avg": 999})
        s.add(Signal(region="TN2", source="google_news", kind="headline", title="A new recovery", observed_at=at, fetched_at=at))
        await s.flush()
        assert (await select_tone(s, "TN2", at, org_id, llm))["method"] == "lexicon"
        # Another workspace's private headlines must never enter global tone.
        s.add(Signal(org_id=org_id, region="TN3", source="private", kind="headline", title="War attack", observed_at=at, fetched_at=at))
        await s.flush()
        assert await select_tone(s, "TN3", at) is None


async def test_world_exposes_regional_fallback_without_leaking_private_estimates(client, auth):
    from sqlalchemy import select

    from app.models import RegionSnapshot

    headers, data = auth
    at = utcnow() - timedelta(minutes=1)
    fixture = json.loads((Path(__file__).parent / "fixtures/news_tone.json").read_text(encoding="utf-8"))
    async with session_scope() as s:
        for code, titles in fixture["headlines"].items():
            for title in titles:
                s.add(Signal(region=code, source="google_news", kind="headline", title=title, observed_at=at, fetched_at=at))
    response = await client.get("/datapool/world?regions=SA,AE", headers=headers)
    assert response.status_code == 200, response.text
    for code in ("SA", "AE"):
        snapshot = response.json()[code]
        assert snapshot["tone"]["method"] == "lexicon"
        assert snapshot["tone"]["source_label"] == "Headlines (lexicon)"
        assert snapshot["tone"]["source_weight"] == .5
        assert any("estimated from headlines" in (x.get("note") or "") for x in snapshot["stale_sources"])
        assert not any("gdelt has no recent data" in (x.get("note") or "") for x in snapshot["stale_sources"])
    async with session_scope() as s:
        estimates = (await s.execute(select(Signal).where(Signal.source == "headline_tone", Signal.org_id == data["orgs"][0]["id"]))).scalars().all()
        assert len(estimates) == 2
        private_ids = {row.id for row in estimates}
        archives = (await s.execute(select(RegionSnapshot))).scalars().all()
        assert not any(x["id"] in private_ids for row in archives for x in row.data.get("signals", []))


async def test_world_model_credit_reservation_refund_and_cached_reads(client, auth, monkeypatch):
    from app.models import Organization
    from app.services.providers import Resolved

    headers, data = auth
    oid = data["orgs"][0]["id"]
    llm = make_llm(ProviderSettings())
    llm.is_dry = False
    llm.model_for = lambda role: "local-test-model"

    async def estimate(**kwargs):
        kwargs["usage"].calls += 1
        return {"avg": -2}

    llm.complete_json = AsyncMock(side_effect=estimate)
    llm.aclose = AsyncMock()
    monkeypatch.setattr("app.services.llm.make_llm", lambda config: llm)
    monkeypatch.setattr("app.services.providers.resolve", AsyncMock(return_value=Resolved(ProviderSettings(provider="openai"), "platform", None)))
    async with session_scope() as s:
        s.add(Signal(region="AE", source="google_news", kind="headline", title="Dubai recovery and investment"))
        org = await s.get(Organization, oid)
        before = org.credits_balance
    response = await client.get("/datapool/world?regions=AE", headers=headers)
    assert response.status_code == 200 and response.json()["AE"]["tone"]["method"] == "model"
    async with session_scope() as s:
        assert (await s.get(Organization, oid)).credits_balance == before - 1
    assert (await client.get("/datapool/world?regions=AE", headers=headers)).status_code == 200
    llm.complete_json.assert_awaited_once()
    async with session_scope() as s:
        assert (await s.get(Organization, oid)).credits_balance == before - 1
        (await s.get(Organization, oid)).credits_balance = 0
    # A connected platform model without credits must still yield a usable lexicon estimate.
    response = await client.get("/datapool/world?regions=AE", headers=headers)
    assert response.status_code == 200
    assert response.json()["AE"]["tone"]["method"] in {"lexicon", "model"}  # Cached model costs nothing.
    llm.complete_json.assert_awaited_once()
