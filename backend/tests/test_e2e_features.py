"""Roadmap features beyond the core five steps, in dry-run mode: content formats (poll, carousel, real video upload),
competitor benchmarking, decision insights, collaboration, version history, transcript, audience templates, branding."""
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

import pytest
from test_e2e_dry import SCRIPT, wait_for

FAST = {"voice": 16, "crowd": 400, "stakeholders": 1, "hours": 2, "minutes_per_round": 60, "listening": False}
SRT = """1
00:00:00,000 --> 00:00:02,500
Stop scrolling: ten minutes is all you need.

2
00:00:02,500 --> 00:00:05,000
Three moves you can do after iftar.

3
00:00:05,000 --> 00:00:08,000
Follow for the full Ramadan plan.
"""


def png(color: tuple[int, int, int]) -> bytes:
    raw = b"".join(b"\x00" + bytes(color) * 8 for _ in range(8))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


async def run_all(client, h, sid):
    assert (await client.post(f"/simulations/{sid}/graph", headers=h)).status_code == 200
    await wait_for(client, h, sid, "status", {"graph_ready"})
    assert (await client.post(f"/simulations/{sid}/environment", headers=h)).status_code == 200
    await wait_for(client, h, sid, "status", {"ready"})
    assert (await client.post(f"/simulations/{sid}/start", headers=h)).status_code == 200
    return await wait_for(client, h, sid, "status", {"completed"})


async def upload(client, h, pid, name, data, mime, kind="content"):
    r = await client.post(f"/projects/{pid}/assets", headers=h, data={"kind": kind}, files={"file": (name, data, mime)})
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_formats_insights_and_collaboration(client, auth):
    h, session = auth
    ref = (await client.get("/reference", headers=h)).json()
    assert {f["key"] for f in ref["formats"]} >= {"short_video", "podcast", "song", "thumbnail", "carousel", "poll", "article"}
    pid = (await client.post("/projects", json={"name": "Formats"}, headers=h)).json()["id"]
    aud = {"regions": ["AE", "SA"]}

    # poll ------------------------------------------------------------------------------------------------------
    bad = await client.post(f"/projects/{pid}/simulations", headers=h, json={"content": {"format": "poll", "text": "Which?", "poll_options": ["A"]}})
    assert bad.status_code == 422
    body = {"name": "Poll", "content": {"format": "poll", "text": "When do you work out during Ramadan?",
                                        "poll_options": ["Before suhoor", "After iftar", "I don't"]}, "audience": aud, "overrides": FAST}
    sim = (await client.post(f"/projects/{pid}/simulations", json=body, headers=h)).json()
    assert sim["content"]["type"] == "text" and sim["content"]["format"] == "poll"
    res = (await run_all(client, h, sim["id"]))["results"]
    poll = res["poll"]
    assert poll and len(poll["share_of_voters"]) == 3 and 0 <= poll["turnout"] <= 1
    assert abs(sum(poll["share_of_voters"]) - 1) < 0.01 or poll["voters_n"] == 0
    assert res["format"]["key"] == "poll" and res["timing"]["best_window_local"] and isinstance(res["recommendations"], list)
    assert res["viral"]["cascade"]["real_world"] is None and res["viral"]["cascade"]["people_runs"]

    # carousel with real images, competitor benchmark -----------------------------------------------------------------
    slides = [await upload(client, h, pid, f"s{i}.png", png(c), "image/png") for i, c in enumerate([(200, 30, 30), (30, 200, 30), (30, 30, 200)])]
    comp = await upload(client, h, pid, "competitor.png", png((90, 90, 90)), "image/png", "content_b")
    body = {"name": "Carousel vs competitor", "audience": aud, "overrides": FAST,
            "content": {"format": "carousel", "title": "Ramadan routine", "asset_ids": slides, "description": "Cover\nMove one\nMove two",
                        "b_kind": "competitor", "variant_b": {"title": "Rival gym post", "asset_id": comp, "description": "Rival offer poster"}}}
    sim = (await client.post(f"/projects/{pid}/simulations", json=body, headers=h)).json()
    s = await run_all(client, h, sim["id"])
    assert len(s["card"]["segments"]) == 3 and s["card"]["format_key"] == "carousel"
    ab = s["results"]["ab"]
    assert ab["kind"] == "competitor" and {"emotion", "novelty", "would_comment"} <= set(ab["a"]) and "(competitor)" not in s["content"]["card_b"]["title"]
    carousel_id = sim["id"]

    # real video file with subtitles (needs ffmpeg) ----------------------------------------------------------------------
    if shutil.which("ffmpeg"):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "clip.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x568:rate=15", "-f", "lavfi",
                            "-i", "sine=frequency=440", "-t", "8", "-shortest", "-pix_fmt", "yuv420p", str(out)], check=True)
            vid = await upload(client, h, pid, "clip.mp4", out.read_bytes(), "video/mp4")
        body = {"name": "Reel", "audience": aud, "overrides": FAST,
                "content": {"format": "short_video", "title": "Ten minute plan", "asset_id": vid, "transcript": SRT}}
        sim = (await client.post(f"/projects/{pid}/simulations", json=body, headers=h)).json()
        s = await run_all(client, h, sim["id"])
        card = s["card"]
        assert card["timed"] and abs(card["duration"] - 8) < 0.6 and card["segments"][0]["start"] == 0
        assert any(seg.get("has_frame") for seg in card["segments"])
        assert s["results"]["heatmap"]["timed"] is True

    # podcast from a script, advanced audience filters --------------------------------------------------------------------
    n_all = (await client.post("/datapool/population/count", json=aud, headers=h)).json()["n"]
    adv = {**aud, "professions": ["manager", "professional"], "incomes": ["upper-middle", "high"], "ocean": {"openness": [0.5, 1.0]}}
    n_adv = (await client.post("/datapool/population/count", json=adv, headers=h)).json()["n"]
    assert 0 < n_adv < n_all
    assert (await client.post("/datapool/population/count", json={**aud, "ocean": {"openness": [0.9, 0.2]}}, headers=h)).status_code == 422
    body = {"name": "Podcast", "audience": adv, "overrides": FAST, "content": {"format": "podcast", "title": "Fasting and fitness", "transcript": SCRIPT}}
    pod = (await client.post(f"/projects/{pid}/simulations", json=body, headers=h)).json()
    s = await run_all(client, h, pod["id"])
    assert s["card"]["format_label"] == "Podcast" and s["results"]["audience"]["size"] == n_adv
    ex = (await client.post(f"/simulations/{pod['id']}/explore", json={"regions": ["AE"]}, headers=h)).json()
    assert ex["peak_hours_local"] and ex["recommendations"] and ex["trust"]["label"] in ("low", "moderate", "high")

    # transcript, annotations, review, versions ---------------------------------------------------------------------------
    t = (await client.get(f"/simulations/{pod['id']}/transcript?limit=5", headers=h)).json()
    assert t["total"] >= 1 and len(t["items"]) <= 5
    t2 = (await client.get(f"/simulations/{pod['id']}/transcript?region=AE", headers=h)).json()
    assert all(i["region"] == "AE" for i in t2["items"])
    a = (await client.post(f"/simulations/{pod['id']}/annotations", json={"anchor": "segment:1", "body": "Product reveal here"}, headers=h)).json()
    assert a["author"] and (await client.post(f"/simulations/{pod['id']}/annotations", json={"anchor": "bogus", "body": "x"}, headers=h)).status_code == 422
    assert (await client.patch(f"/annotations/{a['id']}", json={"resolved": True}, headers=h)).status_code == 200
    rv = (await client.post(f"/simulations/{pod['id']}/review", json={"status": "approved", "note": "Ship it"}, headers=h)).json()
    assert rv["review_status"] == "approved"
    notes = (await client.get(f"/simulations/{pod['id']}/annotations", headers=h)).json()
    assert len(notes) == 2 and notes[0]["resolved"] is True and notes[1]["anchor"] == "review"
    child = (await client.post(f"/simulations/{pod['id']}/clone", json={"mode": "edit", "changes": {"title": "Fasting & fitness, faster"}}, headers=h)).json()
    assert child["content"]["variant_b"]["title"] == "Fasting & fitness, faster"
    rerun = (await client.post(f"/simulations/{pod['id']}/clone", json={"mode": "rerun", "build": True}, headers=h)).json()
    assert rerun["status"] == "building_graph"
    await wait_for(client, h, rerun["id"], "status", {"completed"})
    vs = (await client.get(f"/simulations/{child['id']}/versions", headers=h)).json()
    assert [v["id"] for v in vs][0] == pod["id"] and {child["id"], rerun["id"]} <= {v["id"] for v in vs}

    # benchmark (needs >= 5 other completed runs; this session has them by now) ------------------------------------------------
    b = (await client.get(f"/simulations/{carousel_id}/benchmark", headers=h)).json()
    assert b["available"] is False or 0 <= b["percentile"] <= 100

    # audience templates (persona library) and branding --------------------------------------------------------------------
    tpl = (await client.post("/audience-templates", json={"name": "Gulf professionals", "filters": adv, "shared": True,
                                                          "source_citation": "Arab Barometer wave VIII"}, headers=h)).json()
    assert tpl["mine"] and tpl["filters"]["professions"] == ["manager", "professional"]
    other_org = (await client.post("/orgs", json={"name": "Other studio"}, headers=h)).json()
    h2 = {**h, "X-Org-Id": other_org["id"]}
    community = (await client.get("/audience-templates?scope=community", headers=h2)).json()
    assert any(x["id"] == tpl["id"] and not x["mine"] for x in community)
    assert (await client.delete(f"/audience-templates/{tpl['id']}", headers=h2)).status_code == 404
    assert (await client.post(f"/audience-templates/{tpl['id']}/use", headers=h2)).json()["uses"] == 1
    br = await client.put("/orgs/current/branding", json={"product_name": "Acme Insights", "accent": "#0f766e"}, headers=h)
    assert br.status_code == 200 and (await client.get("/orgs/current/branding", headers=h)).json()["accent"] == "#0f766e"
    assert (await client.put("/orgs/current/branding", json={"accent": "teal"}, headers=h)).status_code == 422
    assert session["user"]["is_superuser"]


def docx(paragraphs: list[str]) -> bytes:
    import io
    import zipfile
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = f'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


FEED = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Rival Gym</title>
<item><guid>a1</guid><title>Rival Gym launches free Ramadan memberships</title><description>Free gym access from iftar to suhoor for the whole month.</description><link>https://example.com/a1</link></item>
<item><guid>a0</guid><title>Older post</title><description>Old news.</description></item>
</channel></rss>"""


@pytest.mark.asyncio
async def test_documents_autopilot_recurring_and_monitoring(client, auth, monkeypatch):
    from datetime import timedelta

    from app.db.base import utcnow
    from app.db.session import session_scope
    from app.models import Simulation
    from app.services import monitoring

    h, session = auth
    pid = (await client.post("/projects", json={"name": "Autopilot"}, headers=h)).json()["id"]
    aud = {"regions": ["AE", "SA"]}

    # a Word document as study material, run end to end on autopilot, with a follower count for real-world reach
    doc = await upload(client, h, pid, "lesson.docx", docx(["Fasting and exercise: a short guide.", "Move gently after iftar.", "Hydrate before suhoor."]),
                       "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    body = {"name": "Lesson", "audience": aud, "overrides": FAST,
            "content": {"format": "study_material", "asset_id": doc, "creator_followers": 120000, "platform": "youtube"}}
    sim = (await client.post(f"/projects/{pid}/simulations", json=body, headers=h)).json()
    assert sim["content"]["type"] == "text"
    assert (await client.post(f"/simulations/{sim['id']}/autopilot", headers=h)).json()["status"] == "graph queued"
    s = await wait_for(client, h, sim["id"], "status", {"completed"})
    assert "Fasting and exercise" in s["card"]["segments"][0]["text"] and s["card"]["title"].startswith("Fasting and exercise")
    rw = s["results"]["viral"]["cascade"]["real_world"]
    assert rw["followers"] == 120000 and rw["first_viewers"] == 12000 and rw["p10"] <= rw["median"] <= rw["p90"]

    # without a follower count there is no real-world estimate
    drafts = []
    for i in range(2):
        b = {"name": f"Draft {i}", "audience": aud, "overrides": FAST, "content": {"format": "social_post", "text": f"Post number {i}. Ten minute workouts after iftar."}}
        drafts.append((await client.post(f"/projects/{pid}/simulations", json=b, headers=h)).json()["id"])
    res = (await client.post(f"/projects/{pid}/batch", json={"simulation_ids": drafts + ["nope"]}, headers=h)).json()["results"]
    assert [r["ok"] for r in res] == [True, True, False]
    for sid in drafts:
        done = await wait_for(client, h, sid, "status", {"completed"})
        assert done["results"]["viral"]["cascade"]["real_world"] is None

    # recurring re-run: schedule, force it due, run the tick
    assert (await client.put(f"/simulations/{drafts[0]}/rerun-schedule", json={"every_days": 7}, headers=h)).json()["rerun_every_days"] == 7
    async with session_scope() as ss:
        row = await ss.get(Simulation, drafts[0])
        row.next_rerun_at = utcnow() - timedelta(minutes=1)
    started = await monitoring.due_reruns()
    assert started == [drafts[0]]
    vs = (await client.get(f"/simulations/{drafts[0]}/versions", headers=h)).json()
    rerun = next(v for v in vs if v["id"] != drafts[0])
    await wait_for(client, h, rerun["id"], "status", {"completed"})

    # competitor monitoring: the private address is refused; a public feed (fetch stubbed) is tested and alerts
    bad = await client.post("/watches", json={"name": "Local", "feed_url": "http://127.0.0.1:8000/feed", "project_id": pid}, headers=h)
    assert bad.status_code == 400 and "private" in bad.json()["error"]["message"]

    async def fake_fetch(url):
        return FEED
    monkeypatch.setattr(monitoring, "fetch", fake_fetch)
    monkeypatch.setattr(monitoring, "check_public_url", lambda url: url)
    # Give the competitor a deterministic baseline to beat without bypassing the
    # public API's nonnegative threshold validation.
    from sqlalchemy import update
    async with session_scope() as ss:
        await ss.execute(update(Simulation).where(Simulation.org_id == session["orgs"][0]["id"]).values(score=0))
    w_response = await client.post("/watches", json={"name": "Rival Gym", "feed_url": "https://example.com/rss", "project_id": pid, "audience": aud,
                                                   "threshold": 0}, headers=h)
    assert w_response.status_code == 200, w_response.text
    w = w_response.json()
    first = (await client.post(f"/watches/{w['id']}/check", headers=h)).json()
    assert first["new"] == 1
    again = (await client.post(f"/watches/{w['id']}/check", headers=h)).json()
    assert again["new"] == 0
    runs = (await client.get(f"/watches/{w['id']}/runs", headers=h)).json()
    assert len(runs) == 1 and runs[0]["source_url"] == "https://example.com/a1"
    await wait_for(client, h, runs[0]["id"], "status", {"completed"})
    alerts = (await client.get("/alerts", headers=h)).json()
    assert alerts["unread"] >= 1 and any(a["kind"] == "competitor_outscored" for a in alerts["items"])
    assert (await client.post("/alerts/read", json={}, headers=h)).status_code == 200
    assert (await client.get("/alerts", headers=h)).json()["unread"] == 0
