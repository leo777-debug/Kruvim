"""Launch forecasts: lock, hash, outcome scoring, comparison and the accuracy record. Comment fixtures are synthetic."""
import asyncio
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.db.session import session_scope
from app.models import LaunchForecast, Simulation
from app.services import launch_forecast as service
from app.services.datapool.connectors.social import YouTubeConnector

TODAY = datetime.now(UTC).date()
POSITIVE = ["Love the new camera, finally a real upgrade", "Amazing battery, pre-ordered already", "Great design, worth it"]
NEGATIVE = ["Same phone again, boring and overpriced", "Disappointing, nothing new, I will skip this one"]


def results(score=6.2, dry=True):
    return {"score": {"mean": score, "low": score - .6, "high": score + .6, "positive": .41, "negative": .18},
            "psychology": {"objections": [{"objection": "too expensive", "n": 9}, {"objection": "no reason to upgrade", "n": 4}]},
            "described_segments": [{"name": "the fans", "description": "loyal buyers", "n": 900, "share_of_audience": .3,
                                    "score": 7.4, "low": 6.9, "high": 7.9, "objection": "", "evidence": {"quote": "x"}},
                                   {"name": "the skeptics", "description": "", "n": 600, "share_of_audience": .2, "score": 4.1,
                                    "low": 3.6, "high": 4.6, "objection": "too expensive"}],
            "provider": {"name": "dryrun" if dry else "openai", "preset": "dryrun", "dry": dry, "voice_model": "dry-run", "report_model": "dry-run"}}


async def make_sim(account, project_id, publish_at=None, started_at=None, score=6.2, dry=True, status="completed"):
    async with session_scope() as s:
        sim = Simulation(org_id=account["orgs"][0]["id"], project_id=project_id, created_by=account["user"]["id"], name="Phone keynote",
                         content={"type": "text", "title": "Phone keynote"}, audience={}, status=status, publish_at=publish_at,
                         started_at=started_at or datetime.now(UTC), finished_at=datetime.now(UTC),
                         results=results(score, dry) if status == "completed" else {})
        s.add(sim)
        await s.flush()
        return sim.id


async def setup(client, auth):
    h, account = auth
    project = (await client.post("/projects", headers=h, json={"name": "Launches"})).json()
    return h, account, project["id"]


def stub_comments(monkeypatch, texts, platform="youtube"):
    calls = []

    async def fake(org_id, video_ids_or_query, after, before, limit):
        calls.append((after, before))
        if not video_ids_or_query:
            return []
        at = (after or before - timedelta(days=3)) + timedelta(hours=5)
        return [{"platform": platform, "text": t, "at": at.isoformat(), "likes": 1, "url": f"https://example.test/{k}"} for k, t in enumerate(texts)]
    monkeypatch.setattr(service, "fetch_youtube" if platform == "youtube" else "fetch_reddit", fake)
    return calls


def body(sim_id=None, **kw):
    return {"company": "Acme", "product": "Phone 18", "announcement_date": str(TODAY - timedelta(days=40)),
            "release_date": str(TODAY - timedelta(days=30)), "simulation_id": sim_id,
            "sources": {"youtube_video_ids": ["vid1"], "window_days": 14}, **kw}


async def test_create_lock_score_and_scoreboard(client, auth, monkeypatch):
    h, account, project_id = await setup(client, auth)
    announced = datetime.combine(TODAY - timedelta(days=40), datetime.min.time(), tzinfo=UTC)
    sim_id = await make_sim(account, project_id, publish_at=announced - timedelta(hours=6))
    created = await client.post("/launch-forecasts", headers=h, json=body(sim_id))
    assert created.status_code == 200, created.text
    f = created.json()
    assert f["status"] == "pending" and f["context_cutoff"].startswith(str(TODAY - timedelta(days=40)))
    outcome = await client.post(f"/launch-forecasts/{f['id']}/outcome", headers=h)
    assert outcome.status_code == 400 and outcome.json()["error"]["code"] == "not_locked"

    locked = await client.post(f"/launch-forecasts/{f['id']}/lock", headers=h)
    assert locked.status_code == 200, locked.text
    f = locked.json()
    assert f["status"] == "locked" and f["hash_valid"] is True and len(f["prediction_hash"]) == 64
    assert f["prediction"]["score"] == 6.2 and f["prediction"]["positive_share"] == .41
    assert f["prediction"]["top_objections"][0] == {"objection": "too expensive", "n": 9}
    assert [seg["name"] for seg in f["prediction"]["segments"]] == ["the fans", "the skeptics"]
    assert "evidence" not in f["prediction"]["segments"][0]
    detail = (await client.get(f"/launch-forecasts/{f['id']}", headers=h)).json()
    assert service.canonical(detail["locked_payload"]) and detail["locked_payload"]["prediction"] == f["prediction"]

    # Locked forecasts are immutable and stay on the record.
    assert (await client.patch(f"/launch-forecasts/{f['id']}", headers=h, json={"product": "Phone 18 Pro"})).status_code == 409
    assert (await client.post(f"/launch-forecasts/{f['id']}/lock", headers=h)).status_code == 409
    assert (await client.delete(f"/launch-forecasts/{f['id']}", headers=h)).status_code == 409

    calls = stub_comments(monkeypatch, POSITIVE + NEGATIVE + ["Love the new camera, finally a real upgrade"])
    scored = await client.post(f"/launch-forecasts/{f['id']}/outcome", headers=h)
    assert scored.status_code == 200, scored.text
    f = scored.json()
    release = datetime.combine(TODAY - timedelta(days=30), datetime.min.time(), tzinfo=UTC)
    assert calls[0][0] == release and calls[0][1] == release + timedelta(days=14)
    assert f["status"] == "scored" and f["outcome"]["n"] == 5 and f["outcome"]["collected"] == 5   # duplicate dropped
    assert f["outcome"]["method"]["dry"] is True and f["outcome"]["method"]["version"] == service.RATER_VERSION
    assert f["outcome"]["window"]["complete"] is True and f["outcome"]["positive_share"] == .6
    assert f["comparison"]["abs_error"] == round(abs(6.2 - f["outcome"]["score"]), 2)
    assert f["hash_valid"] is True   # scoring never touches the locked prediction
    assert not f["counts_toward_record"]
    assert "Dry-run prediction" in f["excluded_because"] and "Model training cutoff not recorded" in f["excluded_because"]

    board = (await client.get("/launch-forecasts/scoreboard", headers=h)).json()
    assert board["by_status"]["scored"] == 1 and board["all"]["n"] == 1 and board["record"]["n"] == 0
    assert "training cutoff" in board["contamination_note"]


async def test_context_after_cutoff_and_unreleased_are_rejected(client, auth):
    h, account, project_id = await setup(client, auth)
    late = await make_sim(account, project_id, publish_at=None, started_at=datetime.now(UTC))
    f = (await client.post("/launch-forecasts", headers=h, json=body(late))).json()
    r = await client.post(f"/launch-forecasts/{f['id']}/lock", headers=h)
    assert r.status_code == 400 and r.json()["error"]["code"] == "context_after_cutoff"

    running = await make_sim(account, project_id, publish_at=datetime.now(UTC) - timedelta(days=60), status="running")
    patched = await client.patch(f"/launch-forecasts/{f['id']}", headers=h, json={"simulation_id": running})
    assert patched.status_code == 200
    assert (await client.post(f"/launch-forecasts/{f['id']}/lock", headers=h)).status_code == 400

    future = body(None, announcement_date=str(TODAY - timedelta(days=2)), release_date=str(TODAY + timedelta(days=30)))
    upcoming = (await client.post("/launch-forecasts", headers=h, json=future)).json()
    r = await client.post(f"/launch-forecasts/{upcoming['id']}/outcome", headers=h)
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_released"
    bad = body(None, release_date=str(TODAY - timedelta(days=50)))
    assert (await client.post("/launch-forecasts", headers=h, json=bad)).status_code == 422


async def test_tampered_prediction_fails_hash_check(client, auth):
    h, account, project_id = await setup(client, auth)
    sim_id = await make_sim(account, project_id, publish_at=datetime.now(UTC) - timedelta(days=90))
    f = (await client.post("/launch-forecasts", headers=h, json=body(sim_id))).json()
    await client.post(f"/launch-forecasts/{f['id']}/lock", headers=h)
    async with session_scope() as s:
        row = await s.get(LaunchForecast, f["id"])
        row.prediction = {**row.prediction, "score": 9.9}
    assert (await client.get(f"/launch-forecasts/{f['id']}", headers=h)).json()["hash_valid"] is False


async def test_record_counts_only_clean_post_cutoff_launches(client, auth, monkeypatch):
    """Live-model predictions locked before release, announced after the model's cutoff, count; contaminated ones do not."""
    import app.api.routes.launch_forecasts as routes
    h, account, project_id = await setup(client, auth)

    async def live_rate(org_id, product, comments):
        return [service.dry_score(c["text"]) for c in comments], {"rater": "stub:model", "dry": False, "version": service.RATER_VERSION}
    monkeypatch.setattr(service, "rate", live_rate)
    comment_sets = [POSITIVE, POSITIVE[:1] + NEGATIVE, NEGATIVE, POSITIVE + NEGATIVE]
    current = {"texts": POSITIVE}

    async def fake(org_id, video_ids, after, before, limit):
        return [{"platform": "youtube", "text": t, "at": (after + timedelta(hours=1)).isoformat(), "likes": 0, "url": None}
                for t in current["texts"]]
    monkeypatch.setattr(service, "fetch_youtube", fake)

    ids = []
    for k, (company, score) in enumerate([("Acme", 7.5), ("Acme", 5.0), ("Globex", 3.5), ("Initech", 6.0)]):
        announced = TODAY - timedelta(days=60 - k)
        sim_id = await make_sim(account, project_id, publish_at=datetime.combine(announced, datetime.min.time(), tzinfo=UTC) - timedelta(days=1),
                                score=score, dry=False)
        cutoff = str(TODAY - timedelta(days=400)) if k < 3 else str(TODAY - timedelta(days=10))   # the last one is contaminated
        f = (await client.post("/launch-forecasts", headers=h, json=body(sim_id, company=company, product=f"Product {k}",
             announcement_date=str(announced), release_date=str(TODAY - timedelta(days=20 - k)), model_knowledge_cutoff=cutoff))).json()
        monkeypatch.setattr(routes, "utcnow", lambda a=announced: datetime.combine(a, datetime.min.time(), tzinfo=UTC) + timedelta(hours=12))
        assert (await client.post(f"/launch-forecasts/{f['id']}/lock", headers=h)).status_code == 200
        monkeypatch.setattr(routes, "utcnow", lambda: datetime.now(UTC))
        current["texts"] = comment_sets[k]
        scored = await client.post(f"/launch-forecasts/{f['id']}/outcome", headers=h)
        assert scored.status_code == 200, scored.text
        ids.append(scored.json())

    first, second, _, contaminated = ids
    assert first["counts_toward_record"] and first["hash_valid"]
    assert second["comparison"]["direction"]["previous_id"] == first["id"]     # Acme's earlier launch, found by company
    assert second["comparison"]["direction"]["predicted"] == "down" and second["comparison"]["direction"]["actual"] == "down"
    assert second["comparison"]["direction"]["correct"] is True
    assert not contaminated["counts_toward_record"]
    assert any("training cutoff" in reason for reason in contaminated["excluded_because"])

    board = (await client.get("/launch-forecasts/scoreboard", headers=h)).json()
    assert board["record"]["n"] == 3 and board["all"]["n"] == 4 and board["record"]["companies"] == 2
    assert board["record"]["direction_n"] == 1 and board["record"]["direction_hit_rate"] == 1.0
    assert board["record"]["spearman"] == 1.0 and board["record"]["mean_abs_error"] is not None


async def test_reference_launch_and_background_respect_cutoff(client, auth, monkeypatch):
    h, _, _ = await setup(client, auth)
    stub_comments(monkeypatch, POSITIVE)
    ref = (await client.post("/launch-forecasts", headers=h, json=body(None, product="Phone 17", announcement_date=str(TODAY - timedelta(days=400)),
                                                                    release_date=str(TODAY - timedelta(days=390))))).json()
    scored = (await client.post(f"/launch-forecasts/{ref['id']}/outcome", headers=h)).json()
    assert scored["status"] == "reference" and scored["outcome"]["n"] == 3 and scored["comparison"] is None

    nxt = (await client.post("/launch-forecasts", headers=h, json=body(None, previous_id=ref["id"], sources={
        "youtube_video_ids": ["new"], "background_video_ids": ["old"]}))).json()
    cutoff = datetime.fromisoformat(nxt["context_cutoff"])

    async def mixed(org_id, video_ids, after, before, limit):
        assert before == cutoff
        return [{"platform": "youtube", "text": "old and fine", "at": (cutoff - timedelta(days=1)).isoformat(), "likes": 0, "url": None},
                {"platform": "youtube", "text": "leaked from after the announcement", "at": cutoff.isoformat(), "likes": 0, "url": None}]
    monkeypatch.setattr(service, "fetch_youtube", mixed)
    bg = await client.post(f"/launch-forecasts/{nxt['id']}/background", headers=h)
    assert bg.status_code == 200, bg.text
    assert bg.json()["n"] == 1 and "old and fine" in bg.json()["seed_text"] and "leaked" not in bg.json()["seed_text"]
    assert (await client.get(f"/launch-forecasts/{nxt['id']}", headers=h)).json()["background"]["n"] == 1


def test_direction_and_eligibility_units():
    prev = LaunchForecast(id="p", company="Acme", product="Phone 17", announcement_date=date(2026, 1, 1), release_date=date(2026, 2, 1),
                          prediction={}, outcome={"score": 6.0})
    cur = LaunchForecast(id="c", company="acme", product="Phone 18", announcement_date=date(2027, 1, 1), release_date=date(2027, 2, 1), simulation_id="s",
                         model_knowledge_cutoff=date(2027, 1, 1), prediction={"score": 6.1, "positive_share": .5}, outcome={"score": 6.9, "positive_share": .6})
    assert service.previous_of(cur, [prev, cur]) is prev
    c = service.compare(cur, prev)
    assert c["abs_error"] == .8 and c["positive_share_error"] == .1
    assert c["direction"]["predicted"] == "flat" and c["direction"]["actual"] == "up" and c["direction"]["correct"] is False
    assert c["direction"]["basis"] == "prediction vs previous launch's actual score"
    assert service.status(prev) == "reference" and service.status(cur) == "pending"
    assert service.eligibility(cur)[0] == "Not locked" and "training cutoff (2027-01-01)" in service.eligibility(cur)[1]
    assert service.dry_score("love it, amazing upgrade") > 6.5 > 4 > service.dry_score("boring and overpriced, worst")


async def test_youtube_comment_threads_window_paging_and_quota(monkeypatch):
    from app.core.config import settings
    from app.services.datapool import limits
    t0 = datetime(2026, 9, 20, tzinfo=UTC)
    pages = {None: (["a", "b"], [t0 + timedelta(days=3), t0 + timedelta(days=2)], "p2"),
             "p2": (["c", "d"], [t0 + timedelta(days=1), t0 - timedelta(days=1)], "p3")}
    seen = []
    limits._spent.clear()

    def handler(request: httpx.Request):
        assert request.url.path.endswith("/commentThreads")
        token = request.url.params.get("pageToken")
        seen.append(token)
        texts, times, nxt = pages[token]
        items = [{"id": f"t{x}", "snippet": {"totalReplyCount": 0, "topLevelComment": {"id": f"c{x}", "snippet": {
            "textDisplay": x, "likeCount": 2, "publishedAt": at.isoformat().replace("+00:00", "Z"), "authorDisplayName": "u"}}}}
            for x, at in zip(texts, times)]
        return httpx.Response(200, json={"items": items, "nextPageToken": nxt})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items = await YouTubeConnector().comments(client, "vid", {"youtube_api_key": "k"}, after=t0, before=t0 + timedelta(days=3))
    assert [i.title for i in items] == ["b", "c"] and seen == [None, "p2"]   # "a" is after the window, "d" ends paging
    assert items[0].url == "https://www.youtube.com/watch?v=vid&lc=cb" and items[0].kind == "social_comment"

    monkeypatch.setattr(settings, "connector_daily_quota_units", {"youtube": 1})
    limits._spent.clear()
    seen.clear()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items = await YouTubeConnector().comments(client, "vid", {"youtube_api_key": "k"})
    assert seen == [None] and len(items) == 2       # the second page would exceed today's budget
    assert not await limits.spend_quota("youtube", 1)
    limits._spent.clear()


async def test_launch_forecast_migration_upgrade_and_downgrade(tmp_path, monkeypatch):
    from app.core.config import settings
    root = Path(__file__).parents[1]
    db = tmp_path / "launch.db"
    monkeypatch.setattr(settings, "database_url", "sqlite+aiosqlite:///" + db.as_posix())
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    await asyncio.to_thread(command.upgrade, cfg, "0013")
    await asyncio.to_thread(command.upgrade, cfg, "head")
    engine = create_engine("sqlite:///" + db.as_posix())
    try:
        assert "launch_forecasts" in inspect(engine).get_table_names()
        assert {"prediction_hash", "context_cutoff", "model_knowledge_cutoff"} <= {c["name"] for c in inspect(engine).get_columns("launch_forecasts")}
        await asyncio.to_thread(command.downgrade, cfg, "0013")
        assert "launch_forecasts" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()
