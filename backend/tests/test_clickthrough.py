"""Regression coverage for fresh installs and regional data/UI integration."""
import os
import subprocess
import sys
from pathlib import Path

import httpx
import numpy as np
import pytest

from app.services.datapool.base import SignalItem
from app.services.datapool.connectors.environment import CalendarConnector
from app.services.datapool.connectors.news import RegionalTrendsConnector, WikipediaConnector
from app.services.datapool.connectors.social import regionalize
from app.services.datapool.safety import safe_title


def test_regional_social_and_weighted_voice_sampling():
    from app.services.creator import weighted_sample
    from app.services.population.generator import generate
    from app.services.population.regions import REGIONS
    items = [SignalItem("social_trend", "*", "#Caturday"), SignalItem("social_trend", "*", "Riyadh gaming festival")]
    localized = regionalize(items, [{"code": "SA"}, {"code": "AE"}])
    assert [(x.region, x.title) for x in localized] == [("SA", "Riyadh gaming festival")]
    pop = generate(40000, 19)
    chosen, _ = weighted_sample(pop, np.ones(pop.n, bool), 200, np.random.default_rng(1),
                               {"countries": {"SA": 70, "AE": 30}, "genders": {"female": 80, "male": 20}})
    sa = [r["code"] for r in REGIONS].index("SA")
    assert np.mean(pop.region[chosen] == sa) == pytest.approx(.7, abs=.025)
    assert np.mean(pop.male[chosen] == 0) == pytest.approx(.8, abs=.025)
    assert len(set(pop.region[chosen[:10]])) == 2


async def test_country_trends_and_wikipedia_category_safety():
    def handle(request):
        if "trends.google.com" in request.url.host:
            assert request.url.params["geo"] in ("SA", "AE")
            return httpx.Response(200, content=b'<rss xmlns:ht="https://trends.google.com/trending/rss"><channel><item><title>Gaming festival</title><ht:approx_traffic>20K+</ht:approx_traffic></item></channel></rss>')
        return httpx.Response(200, json={"query": {"pages": {"1": {"title": "Ordinary name", "categories": [{"title": "Category:Pornographic actors"}]},
                                                              "2": {"title": "Saudi Arabia", "categories": [{"title": "Category:Countries"}]}}}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        items = await RegionalTrendsConnector().fetch(client, [{"code": "SA"}, {"code": "AE"}], {}, {})
        assert {x.region for x in items} == {"SA", "AE"} and all(x.value == 20000 for x in items)
        allowed = await WikipediaConnector().safe_pages(client, "en", ["Ordinary name", "Saudi Arabia"])
        assert allowed == {"Saudi Arabia"}
    for title in ("Pornhub", "Pornography", "Adult film", "إباحية", "Hentai"):
        assert not safe_title(title)
    assert safe_title("Saudi gaming tournament")


async def test_calendar_no_event_is_not_missing_source():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(204))) as client:
        events = await CalendarConnector().fetch(client, [{"code": "SA", "holiday_cc": "SA"}], {}, {})
    assert events and all(x.region == "SA" for x in events)


async def test_monitoring_real_plan_limits():
    from types import SimpleNamespace

    from app.services.monitoring import WATCH_LIMITS, watch_limit
    for name, limit in WATCH_LIMITS.items():
        assert watch_limit(SimpleNamespace(plan=name), False) == limit


async def test_report_completion_is_visible_after_commit(client, auth, monkeypatch):
    from unittest.mock import AsyncMock

    from app.db.session import session_scope
    from app.models import Simulation
    from app.services.events import bus
    from app.workers import tasks
    h, _ = auth
    project = (await client.post("/projects", headers=h, json={"name": "Report race"})).json()
    sim = (await client.post(f"/projects/{project['id']}/simulations", headers=h, json={"content": {"format": "social_post", "text": "Test"}})).json()
    observed = []
    async def emit(sid, event, payload):
        if event == "report.completed":
            async with session_scope() as s:
                observed.append((await s.get(Simulation, sid)).report_status)
    monkeypatch.setattr(bus, "publish", emit)
    monkeypatch.setattr(tasks, "generate_report_fn", AsyncMock())
    await tasks.generate_report({}, sim["id"])
    assert observed == ["done"]


@pytest.mark.parametrize("legacy", [False, True])
def test_seed_then_startup_migration(tmp_path, legacy):
    backend = Path(__file__).resolve().parents[1]
    env = {**os.environ, "KRUVIM_DATABASE_URL": "sqlite+aiosqlite:///" + (tmp_path / "fresh.db").as_posix(),
           "KRUVIM_DATA_DIR": str(tmp_path), "KRUVIM_ENV": "test"}
    if legacy:
        script = "import asyncio; from app.db.session import engine; from app.models import Base\nasync def run():\n async with engine.begin() as c: await c.run_sync(Base.metadata.create_all)\nasyncio.run(run())"
        subprocess.run([sys.executable, "-c", script], cwd=backend, env=env, check=True, capture_output=True)
    subprocess.run([sys.executable, "-m", "scripts.seed_demo"], cwd=backend, env=env, check=True, capture_output=True)
    subprocess.run([sys.executable, "-c", "from app.db.migrate import upgrade_head; upgrade_head()"],
                   cwd=backend, env=env, check=True, capture_output=True)
