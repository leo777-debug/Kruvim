"""World Monitor protocol and evidence tests use synthetic headlines only."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.session import session_scope
from app.models import DataSource
from app.services.datapool.base import MissingCredentials
from app.services.datapool.connectors.world_monitor import WorldMonitorConnector, refresh_due
from app.services.datapool.context import build_snapshot_data
from app.services.datapool.runner import store_signals
from app.services.sources import ensure_sources

REGIONS = [{"code": "AE-DXB", "country": "AE"}, {"code": "AE-AUH", "country": "AE"}, {"code": "GB"}]
KEY = {"world_monitor_api_key": "synthetic-test-credential"}


def article(title="Synthetic UAE news", **changes):
    return {"title": title, "source": "Fixture Publisher", "link": "https://example.org/news",
            "publishedAt": str(int((datetime.now(UTC) - timedelta(minutes=15)).timestamp() * 1000)), **changes}


async def fetch(items, *, state="complete"):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"state": state, "countries": {"AE": {"items": items}}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await WorldMonitorConnector().fetch(client, REGIONS, KEY, {})
    return result, calls


async def test_one_authenticated_request_preserves_dates_publisher_and_country_scope():
    fixture = article()
    items, calls = await fetch([fixture, fixture])
    assert len(calls) == 1
    assert calls[0].url.params.get_list("country_codes") == ["AE", "GB"]
    assert calls[0].headers["X-WorldMonitor-Key"] == KEY["world_monitor_api_key"]
    assert {item.region for item in items} == {"AE-DXB", "AE-AUH"}
    assert all(item.payload["geography_match"] == "country" for item in items)
    assert all(item.lang is None and "Fixture Publisher" in item.title for item in items)
    assert items[0].observed_at.timestamp() == int(fixture["publishedAt"]) / 1000
    local, _ = await fetch([article("Synthetic Dubai news")], state="partial")
    assert [item.region for item in local] == ["AE-DXB"]
    assert local[0].payload["coverage_state"] == "partial"


async def test_undated_old_future_invalid_links_and_empty_articles_are_excluded():
    now = datetime.now(UTC)
    items, _ = await fetch([
        article(publishedAt=None), article(publishedAt=int((now - timedelta(days=2)).timestamp() * 1000)),
        article(publishedAt=int((now + timedelta(hours=1)).timestamp() * 1000)),
        article(link="javascript:alert(1)"), article(source=""),
    ])
    assert items == []
    with pytest.raises(ValueError, match="unavailable"):
        await fetch([], state="unavailable")


async def test_credentials_and_upstream_errors_are_visible_without_secret_text():
    async with httpx.AsyncClient() as client:
        with pytest.raises(MissingCredentials):
            await WorldMonitorConnector().fetch(client, REGIONS, {}, {})
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(401))) as client:
        with pytest.raises(httpx.HTTPStatusError) as error:
            await WorldMonitorConnector().fetch(client, REGIONS, KEY, {})
    assert KEY["world_monitor_api_key"] not in str(error.value)


async def test_approved_headlines_enter_normal_snapshot_and_reimports_deduplicate(monkeypatch):
    items, _ = await fetch([article("Synthetic Dubai news")])
    monkeypatch.setattr(settings, "env", "production")
    assert await store_signals("world_monitor", items) == 0
    async with session_scope() as session:
        await ensure_sources(session)
        source = (await session.execute(select(DataSource).where(DataSource.key == "world_monitor"))).scalar_one()
        source.status, source.licence_approved = "active", True
    assert await store_signals("world_monitor", items) == 1
    assert await store_signals("world_monitor", items) == 0
    snapshot = await build_snapshot_data("AE-DXB", datetime.now(UTC))
    news = next(item for item in snapshot["news"] if item["source"] == "world_monitor")
    assert news["url"] == "https://example.org/news"
    assert "Fixture Publisher" in news["title"] and news["provenance"]["production_eligible"]


async def test_hosted_check_claims_hourly_run(monkeypatch):
    run = AsyncMock(return_value={"status": "ok", "items": 1})
    monkeypatch.setattr("app.services.datapool.runner.run_connector", run)
    assert (await refresh_due())["status"] == "ok"
    assert (await refresh_due())["status"] == "not_due"
    run.assert_awaited_once_with("world_monitor")
