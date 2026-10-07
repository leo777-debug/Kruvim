"""The five-step workflow through the real OpenAI-compatible provider path, against tools/mock_openai_server.py.

Covers what dry-run cannot: JSON-mode requests, parsing of fenced / <think>-wrapped replies, usage metering, the ReAct
report loop, in-character chat and survey summaries. Runs in its own workspace so the dry-run tests are unaffected."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from test_e2e_dry import SCRIPT, wait_for

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def mock_llm():
    port = _free_port()
    proc = subprocess.Popen([sys.executable, str(ROOT / "tools" / "mock_openai_server.py")], env={**os.environ, "MOCK_PORT": str(port)},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}/v1"
    for _ in range(100):
        try:
            if httpx.get(base + "/models", timeout=0.5).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("mock model server did not start")
    yield base
    proc.kill()


@pytest.mark.asyncio
async def test_workflow_with_openai_compatible_provider(client, auth, mock_llm):
    h0, _ = auth
    org = (await client.post("/orgs", json={"name": "Provider test"}, headers=h0)).json()
    h = {**h0, "X-Org-Id": org["id"]}

    cfg = {"preset": "custom", "base_url": mock_llm, "api_key": "test-key", "voice_model": "mock-small", "report_model": "mock-large",
           "concurrency": 8, "json_mode": True, "price_in": 0.27, "price_cached": 0.07, "price_out": 1.1}
    t = (await client.post("/providers/test", json=cfg, headers=h)).json()
    assert t["ok"], t
    r = await client.put("/providers", json=cfg, headers=h)
    assert r.status_code == 200, r.text
    bad = (await client.post("/providers/test", json={**cfg, "api_key": "wrong"}, headers=h)).json()
    assert not bad["ok"]

    pr = (await client.post("/projects", json={"name": "Provider path"}, headers=h)).json()
    body = {"name": "Mock model run", "requirement": "Will Gulf professionals share this?",
            "content": {"type": "video", "title": "3-minute apartment workout", "platform": "tiktok", "transcript": SCRIPT},
            "audience": {"regions": ["AE", "SA"], "age_min": 18, "age_max": 44},
            "overrides": {"voice": 12, "crowd": 500, "stakeholders": 2, "hours": 3, "minutes_per_round": 60, "listening": False}}
    sid = (await client.post(f"/projects/{pr['id']}/simulations", json=body, headers=h)).json()["id"]

    assert (await client.post(f"/simulations/{sid}/graph", headers=h)).status_code == 200
    s1 = await wait_for(client, h, sid, "status", {"graph_ready"})
    assert s1["card"]["analysed_by"] == "mock-large" and s1["card"]["segments"][0]["label"] == "Part 1"
    assert s1["ontology"]["by"] == "mock-large" and len(s1["ontology"]["entity_types"]) == 7

    assert (await client.post(f"/simulations/{sid}/environment", headers=h)).status_code == 200
    s2 = await wait_for(client, h, sid, "status", {"ready"})
    assert s2["config"]["events"]["scheduled"] and s2["config"]["events"]["hot_topics"] == ["ramadan routines", "home fitness"]

    assert (await client.post(f"/simulations/{sid}/start", headers=h)).status_code == 200
    s3 = await wait_for(client, h, sid, "status", {"completed"})
    res = s3["results"]
    assert res["provider"]["dry"] is False and res["usage"]["calls"] > 12 and res["usage"]["failed"] == 0
    assert res["usage"]["cost_usd"] > 0

    s4 = await wait_for(client, h, sid, "report_status", {"done"})
    rep = (await client.get(f"/simulations/{sid}/report", headers=h)).json()
    assert rep["title"] == "Mock report" and len(rep["sections"]) == 3
    assert all(len(sec["tools"]) >= 2 for sec in rep["sections"]) and "Mock section" in rep["markdown"]
    rw = (await client.get(f"/simulations/{sid}", headers=h)).json()["results"]["rewrites"]
    assert len(rw["titles"]) == 3 and rw["hook"]["text"] and rw["edits"]

    agent = next(a for a in (await client.get(f"/simulations/{sid}/agents", headers=h)).json() if a["kind"] == "voice")
    chat = (await client.post(f"/simulations/{sid}/agents/{agent['ref']}/chat", json={"message": "Why that score?"}, headers=h)).json()
    assert "short format" in chat["chat"][-1]["content"]
    ans = (await client.post(f"/simulations/{sid}/report/chat", json={"message": "Who should I target?"}, headers=h)).json()
    assert "Mock section" in ans["answer"]

    usage = (await client.get("/usage", headers=h)).json()
    assert usage["provider_source"] == "org" and usage["metered"] is False
    assert sum(m["calls"] for m in usage["month"]) >= res["usage"]["calls"]
    assert s4["status"] == "completed"
