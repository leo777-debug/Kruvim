"""Creator weighting, connection security, sync idempotency and honest accuracy reporting."""
from datetime import timedelta
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import httpx
import numpy as np
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import settings
from app.db.base import utcnow
from app.db.session import session_scope
from app.models import PerformanceReport, Simulation, SocialConnection, SocialPost
from app.schemas.creator import FollowerSplit
from app.services import social
from app.services.accuracy import summarize
from app.services.creator import PRESETS, audience_weights
from app.services.datapool.retrieval import embed, rank
from app.services.population.generator import generate
from app.services.population.regions import REGIONS
from app.services.source_weights import weights_from_pairs


def test_follower_split_validation():
    for split in ({"countries": {"SA": 90}}, {"genders": {"male": float("nan")}}, {"ages": {"18-24": 50, "20-34": 50}}):
        with pytest.raises(ValidationError):
            FollowerSplit(**split)
    assert FollowerSplit(countries={"SA": 70, "AE": 30}).countries["SA"] == 70


def test_twin_weights_preserve_marginals_and_expose_limits():
    pop = generate(10000, 7)
    indices = np.arange(pop.n)
    w, diagnostics = audience_weights(pop, indices, {"countries": {"SA": 65, "AE": 35}, "genders": {"female": 80, "male": 20},
                                                   "ages": {"18-24": 40, "25-34": 60}})
    sa = [r["code"] for r in REGIONS].index("SA")
    assert w[pop.region == sa].sum() == pytest.approx(.65, abs=.002)
    assert w[pop.male == 0].sum() == pytest.approx(.8, abs=.002)
    assert w[(pop.age >= 18) & (pop.age <= 24)].sum() == pytest.approx(.4, abs=.002)
    _, limited = audience_weights(pop, indices, {"countries": {"SA": 50, "ZZ": 50}})
    assert limited["coverage"]["countries"] == 50 and limited["warning"]
    assert diagnostics["max_marginal_error_percent"] < .2
    for preset in PRESETS:
        assert pop.mask(preset["filters"]).any()


def test_retrieval_weights_and_tied_correlations():
    from app.api.routes.platform import _spearman
    signals = [{"id": 1, "source": "weather", "title": "summer weather"},
               {"id": 2, "source": "news", "title": "gaming tournament esports"}]
    assert rank(signals, "gaming esports")[0]["id"] == 2
    assert np.array_equal(embed("gaming esports"), embed("gaming esports"))
    assert _spearman([1, 1, 1], [1, 2, 3]) is None
    assert _spearman([1, 1, 2], [2, 2, 3]) == 1
    assert weights_from_pairs([(["news"], True)], 3)["news"]["weight"] == 1
    assert weights_from_pairs([(["news"], True)] * 3, 3)["news"]["weight"] == 1.5
    assert summarize([])["accuracy_percent"] is None
    assert summarize([("A", "A"), ("A", "B")])["accuracy_percent"] == 50


def test_storage_rejects_sibling_prefix_escape():
    from app.services.storage import _local_path
    with pytest.raises(ValueError):
        _local_path("../objects-escape/private.txt")
    with pytest.raises(ValueError):
        _local_path("../secret.txt")
    assert _local_path("workspace/asset.txt").endswith("asset.txt")


async def test_provider_refresh_and_counts_without_comments():
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path.endswith("oauth/token/"):
            return httpx.Response(200, json={"access_token": "new", "refresh_token": "rotated", "expires_in": 7200})
        return httpx.Response(200, json={"data": {"videos": [{"id": "123", "create_time": 1700000000,
            "view_count": 100, "like_count": 0, "share_count": 0, "comment_count": 0}]}, "error": {"code": "ok"}})
    c = SocialConnection(platform="tiktok", expires_at=utcnow() - timedelta(seconds=1))
    social.save_tokens(c, {"access_token": "old", "refresh_token": "refresh", "expires_in": 1})
    c.expires_at = utcnow() - timedelta(seconds=1)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        token = await social.access_token(client, c)
        metrics, published = await social.outcome(client, c, "123", token)
    assert token == "new" and published
    assert metrics["engagement_rate"] == 0 and metrics["retention"] is None
    assert all("comment/list" not in str(r.url) for r in calls)
    assert calls[-1].headers["Authorization"] == "Bearer new"


async def test_connections_oauth_replay_tenant_isolation_and_sync(client, auth, monkeypatch):
    from app.services.social_sync import sync_connection
    h, session = auth
    monkeypatch.setattr(settings, "tiktok_client_id", "test-client")
    monkeypatch.setattr(settings, "tiktok_client_secret", "test-secret")
    r = await client.post("/social/tiktok/connect", headers=h)
    assert r.status_code == 200, r.text
    state = parse_qs(urlparse(r.json()["url"]).query)["state"][0]
    monkeypatch.setattr(social, "exchange", AsyncMock(return_value={"access_token": "private-token", "refresh_token": "private-refresh", "expires_in": 3600}))
    monkeypatch.setattr(social, "identity", AsyncMock(return_value=("owner-id", "Creator")))
    assert (await client.get("/social/tiktok/callback", params={"code": "test-code", "state": state})).status_code == 303
    assert (await client.get("/social/tiktok/callback", params={"code": "test-code", "state": state})).status_code == 400
    listed = await client.get("/social/connections", headers=h)
    assert "private-token" not in listed.text and "state_hash" not in listed.text
    connection = listed.json()["connections"][0]
    other = (await client.post("/auth/register", json={"email": "creator-other@example.com", "password": "correct-horse-battery", "org_name": "Other"})).json()
    oh = {"Authorization": f"Bearer {other['access_token']}"}
    assert (await client.post(f"/social/connections/{connection['id']}/sync", headers=oh)).status_code == 404
    assert (await client.get("/social/connections", headers=oh)).json()["connections"] == []
    project = (await client.post("/projects", headers=h, json={"name": "Analytics"})).json()
    created = (await client.post(f"/projects/{project['id']}/simulations", headers=h, json={"content": {"format": "short_video", "platform": "tiktok", "transcript": "A hook"}})).json()
    org_id = session["orgs"][0]["id"]
    finished = utcnow() - timedelta(days=9)
    async with session_scope() as s:
        sim = await s.get(Simulation, created["id"])
        sim.status, sim.finished_at = "completed", finished
        sim.results = {"score": {"first_impression": 7}, "provider": {"dry": False}, "ab": {"winner": "A", "a": {"score": 7}, "b": {"score": 4}}}
    published = utcnow() - timedelta(days=7, hours=3)
    monkeypatch.setattr(social, "outcome", AsyncMock(return_value=({"views": 1000, "likes": 100, "shares": 10, "comments": 1,
        "retention": None, "engagement_rate": 11.1}, published)))
    monkeypatch.setattr(social, "audience", AsyncMock(return_value={"countries": {"SA": 100}, "ages": {}, "genders": {}}))
    for variant, post_id in (("A", "123"), ("B", "456")):
        r = await client.post(f"/simulations/{created['id']}/published-posts", headers=h,
            json={"connection_id": connection["id"], "variant": variant, "post_id": post_id})
        assert r.status_code == 200, r.text
    duplicate = await client.post(f"/simulations/{created['id']}/published-posts", headers=h,
        json={"connection_id": connection["id"], "variant": "A", "post_id": "123"})
    assert duplicate.status_code == 409
    assert await sync_connection(connection["id"], org_id)
    assert (await client.post(f"/social/connections/{connection['id']}/use-audience", headers=h)).status_code == 200
    monkeypatch.setattr(social, "audience", AsyncMock(return_value={"countries": {"SA": 80, "AE": 20}, "ages": {}, "genders": {}}))
    assert await sync_connection(connection["id"], org_id)
    assert (await client.get("/my-audience", headers=h)).json()["profile"]["split"]["countries"] == {"SA": 80, "AE": 20}
    async with session_scope() as s:
        reports = (await s.execute(select(PerformanceReport).where(PerformanceReport.simulation_id == created["id"]))).scalars().all()
        assert len(reports) == 2
        b = (await s.execute(select(SocialPost).where(SocialPost.simulation_id == created["id"], SocialPost.variant == "B"))).scalar_one()
        b.metrics = {**b.metrics, "views": 100}
    result = (await client.get("/accuracy", headers=h)).json()
    assert result["n"] == 1 and result["accuracy_percent"] == 100
    public = (await client.get("/public/accuracy")).json()
    assert public["accuracy_percent"] is None and public["n"] is None
    assert (await client.get("/accuracy", headers=oh)).json()["n"] == 0


async def test_creator_dry_workflow(client, auth, monkeypatch):
    from test_e2e_dry import SCRIPT, wait_for

    from app.services import datapool
    h, _ = auth
    snapshot = {"SA": {"name": "Saudi Arabia", "city": "Riyadh", "brief": "Gaming is topical.", "signals": [
        {"id": 1, "source": "news", "title": "Gaming competition", "at": utcnow().isoformat()}],
        "stale_sources": [{"region": "SA", "source": "news", "age_hours": 9, "stale": True}]}}
    monkeypatch.setattr(datapool, "snapshots_at", AsyncMock(return_value=snapshot))
    assert (await client.put("/my-audience", headers=h, json={"split": {"countries": {"SA": 100}, "genders": {"female": 75, "male": 25}}})).status_code == 200
    project = (await client.post("/projects", headers=h, json={"name": "Creator dry"})).json()
    presets = (await client.get("/audience-presets", headers=h)).json()
    sim = (await client.post(f"/projects/{project['id']}/simulations", headers=h, json={
        "content": {"format": "short_video", "platform": "tiktok", "transcript": SCRIPT},
        "audience": {**presets[1]["filters"], "use_creator_audience": True},
        "overrides": {"voice": 16, "crowd": 100, "hours": 1, "stakeholders": 0, "listening": False}})).json()
    sid = sim["id"]
    for action, state in (("graph", "graph_ready"), ("environment", "ready"), ("start", "completed")):
        assert (await client.post(f"/simulations/{sid}/{action}", headers=h)).status_code == 200
        completed = await wait_for(client, h, sid, "status", {state})
    result = completed["results"]["creator"]
    assert result["short_video"]["rewatch_probability"] > 0
    assert result["agent_signals"] and all(result["agent_signals"].values())
    assert result["stale_sources"][0]["age_hours"] == 9
    assert "language_fit" in result and "trend" in completed["results"]
    # The completion event precedes the follow-up memory write by a few milliseconds.
    import asyncio
    for _ in range(20):
        memory = (await client.get("/my-audience", headers=h)).json()["memory"]
        if any(x["simulation_id"] == sid for x in memory.get("observations", [])):
            break
        await asyncio.sleep(.05)
    assert any(x["simulation_id"] == sid for x in memory["observations"])
    assert (await client.delete("/my-audience/memory", headers=h)).status_code == 200
    assert (await client.get("/my-audience", headers=h)).json()["memory"] == {}


async def test_private_signals_and_snapshot_freshness(client, auth):
    from app.models import Signal, SignalEmbedding
    from app.services.datapool.base import SignalItem
    from app.services.datapool.context import build_snapshot_data
    from app.services.datapool.runner import store_signals
    h, session = auth
    oid = session["orgs"][0]["id"]
    item = SignalItem("headline", "SA", "Private creator brand signal")
    assert await store_signals("targeted", [item], oid) == 1
    assert await store_signals("targeted", [item], oid) == 0
    other = (await client.post("/auth/register", json={"email": "signal-other@example.com", "password": "correct-horse-battery", "org_name": "Signals Other"})).json()
    oh = {"Authorization": f"Bearer {other['access_token']}"}
    assert "Private creator brand signal" not in (await client.get("/datapool/signals", headers=oh)).text
    assert "Private creator brand signal" in (await client.get("/datapool/signals", headers=h)).text
    async with session_scope() as s:
        s.add(Signal(source="google_news", kind="headline", region="SA", title="Old public headline", observed_at=utcnow()-timedelta(hours=9)))
    snapshot = await build_snapshot_data("SA", utcnow())
    assert all(x["title"] != item.title for x in snapshot["signals"])
    assert any(x["source"] == "google_news" and x["age_hours"] >= 9 for x in snapshot["stale_sources"])
    async with session_scope() as s:
        assert (await s.execute(select(SignalEmbedding).where(SignalEmbedding.org_id == oid))).scalars().first()


async def test_archive_roundtrip_and_trend_lifecycle(client, monkeypatch):
    from app.models import RegionSnapshot
    from app.services import storage
    from app.services.datapool.archive import compress_old, load
    from app.services.datapool.context import trend_phase
    objects = {}
    async def put(key, data):
        objects[key] = data
    async def get(key):
        return objects[key]
    monkeypatch.setattr(storage, "put", put)
    monkeypatch.setattr(storage, "get", get)
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "s3_bucket", "test")
    async with session_scope() as s:
        row = RegionSnapshot(region="SA", hour=utcnow()-timedelta(days=40), data={"news": [{"title": "Archived original"}]}, brief="Original context")
        s.add(row)
    assert await compress_old() >= 1
    async with session_scope() as s:
        saved = await s.get(RegionSnapshot, row.id)
        assert saved.data == {} and saved.archive_key
        assert (await load(saved))["news"][0]["title"] == "Archived original"
    assert trend_phase([]) == "unknown"
    assert trend_phase([{"value": x} for x in (10, 15, 25)]) == "rising"
    assert trend_phase([{"value": x} for x in (10, 15, 15)]) == "peaking"
    assert trend_phase([{"value": x} for x in (10, 25, 12)]) == "past its peak"


async def test_one_remote_embedding_batch_and_fallback(client, auth, monkeypatch):
    from types import SimpleNamespace

    from app.services.datapool.retrieval import prepare_retrieval
    from app.services.llm import Usage
    real_client = httpx.AsyncClient
    calls = []
    def response(request):
        import json
        calls.append(request)
        body = json.loads(request.content)
        return httpx.Response(200, json={"data": [{"index": i, "embedding": embed(text).tolist()} for i, text in enumerate(body["input"])],
                                         "usage": {"total_tokens": 20}})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(response), **kwargs))
    monkeypatch.setattr(settings, "embedding_model", "test-embedding")
    monkeypatch.setattr(settings, "embedding_price_per_million", .1)
    llm = SimpleNamespace(is_dry=False, s=SimpleNamespace(provider="openai", base_url="https://example.test/v1", api_key="private"))
    usage = Usage()
    personas = [{"region": "SA", "age": 20, "platforms": ["TikTok"], "interests": [{"label": "Gaming"}]}]
    evidence, meta = await prepare_retrieval(auth[1]["orgs"][0]["id"], personas, {"title": "Gaming"}, {"SA": {"signals": [{"id": 987654, "title": "Gaming esports"}]}}, llm, usage)
    assert len(calls) == 1 and usage.calls == 1 and evidence[0][0]["id"] == 987654
    assert meta["extra_cost_usd"] > 0


async def test_source_learning_requires_independent_workspaces_per_source(client, monkeypatch):
    from app.services.source_weights import learned_weights
    monkeypatch.setattr(settings, "source_weight_min_tests", 3)
    monkeypatch.setattr(settings, "accuracy_min_workspaces", 3)
    connections = []
    for i in range(3):
        account = (await client.post("/auth/register", json={"email": f"source-{i}@example.com",
            "password": "correct-horse-battery", "org_name": f"Source {i}"})).json()
        h = {"Authorization": f"Bearer {account['access_token']}"}
        oid = account["orgs"][0]["id"]
        project = (await client.post("/projects", headers=h, json={"name": "Source learning"})).json()
        sim = (await client.post(f"/projects/{project['id']}/simulations", headers=h,
            json={"content": {"format": "short_video", "platform": "tiktok", "transcript": "Test"}})).json()
        async with session_scope() as s:
            c = SocialConnection(org_id=oid, platform="tiktok", share_accuracy=True)
            s.add(c)
            await s.flush()
            connections.append(c.id)
            predicted_at = utcnow()
            for variant, score, views in (("A", 7, 100), ("B", 4, 10)):
                s.add(SocialPost(org_id=oid, connection_id=c.id, simulation_id=sim["id"], variant=variant,
                    post_id=f"source-{i}-{variant}", predicted_score=score, predicted_at=predicted_at,
                    prediction={"dry": False, "b_kind": "version", "winner": "A", "niche": "source-isolation-test",
                                "sources": ["shared", "single-workspace"] if i == 0 else ["shared"]},
                    metrics={"views": views, "window_eligible": True}))
    async with session_scope() as s:
        result = await learned_weights(s, "source-isolation-test")
        assert result["sources"]["shared"]["weight"] == 1.5
        assert "single-workspace" not in result["sources"]
        (await s.get(SocialConnection, connections[0])).share_accuracy = False
    async with session_scope() as s:
        assert (await learned_weights(s, "source-isolation-test"))["sources"] == {}
