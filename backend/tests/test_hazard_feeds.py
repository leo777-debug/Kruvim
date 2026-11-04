"""Synthetic natural-event fixtures only."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.session import session_scope
from app.models import DataSource
from app.services.datapool.connectors.hazards import EonetConnector, UsgsConnector, current_hazards, nearby
from app.services.datapool.context import build_snapshot_data, snapshots_at, weighted_context
from app.services.datapool.runner import store_signals
from app.services.sources import ensure_sources

REGIONS = [{"code": "AE-DXB", "city": "Dubai", "lat": 25.2, "lon": 55.3},
           {"code": "GB", "city": "London", "lat": 51.5, "lon": -.1}]


def feed(now):
    return {"features": [{"id": "fixture-quake", "properties": {"mag": 5, "place": "Synthetic location",
        "time": int((now - timedelta(hours=1)).timestamp() * 1000)},
        "geometry": {"type": "Point", "coordinates": [55.4, 25.3, 10]}}]}


async def test_usgs_one_request_locality_dates_and_invalid_records():
    now = datetime.now(UTC)
    data, calls = feed(now), []
    data["features"] += [{"id": "missing"}, {"id": "future", "properties": {"mag": 6, "time": int((now + timedelta(days=1)).timestamp()*1000)},
        "geometry": {"type": "Point", "coordinates": [55.4, 25.3]}}]
    def response(request):
        calls.append(request)
        return httpx.Response(200, json=data)
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        items = await UsgsConnector().fetch(client, REGIONS, {}, {})
    assert len(calls) == len(items) == 1
    assert items[0].region == "AE-DXB" and items[0].payload["magnitude"] == 5
    assert items[0].observed_at < now and "does not establish local impact" in items[0].title
    assert not nearby(REGIONS, [999, 25], 500)
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError):
            await UsgsConnector().fetch(client, REGIONS, {}, {"radius_km": 9000})


async def test_eonet_open_latest_geometry_and_sources():
    now = datetime.now(UTC)
    event = {"id": "fixture-storm", "title": "Synthetic storm", "closed": None,
        "categories": [{"id": "severeStorms"}], "sources": [{"id": "fixture", "url": "https://example.org"}],
        "geometry": [{"date": (now - timedelta(hours=1)).isoformat(), "type": "Point", "coordinates": [55.4, 25.3]}]}
    data = {"events": [event, {**event, "closed": now.isoformat()},
        {**event, "geometry": [{"date": now.isoformat(), "type": "Polygon", "coordinates": []}]}]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=data))) as client:
        items = await EonetConnector().fetch(client, REGIONS, {}, {})
    assert len(items) == 1 and items[0].payload["category"] == "severeStorms"
    assert items[0].payload["sources"] == event["sources"]


def test_expired_latest_revision_does_not_restore_old_revision():
    now = datetime.now(UTC)
    def row(expiry):
        return SimpleNamespace(kind="natural_hazard", source="usgs", region="AE-DXB", id=1,
            payload={"event_id": "fixture", "expires_at": expiry.isoformat()})
    assert not current_hazards([row(now-timedelta(minutes=1)), row(now+timedelta(hours=1))], now)
    assert len(current_hazards([row(now+timedelta(hours=1))]*2, now)) == 1


async def test_storage_snapshot_revisions_and_source_gating(monkeypatch):
    now = datetime.now(UTC)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=feed(now)))) as client:
        items = await UsgsConnector().fetch(client, REGIONS, {}, {})
    async with session_scope() as s:
        await ensure_sources(s)
        source = (await s.execute(select(DataSource).where(DataSource.key == "usgs_earthquakes"))).scalar_one()
        assert not source.licence_approved
        source.status, source.licence_approved = "active", True
    assert await store_signals("usgs_earthquakes", items) == 1
    assert await store_signals("usgs_earthquakes", items) == 1
    data = await build_snapshot_data("AE-DXB", datetime.now(UTC))
    assert len(data["natural_hazards"]) == 1
    assert len([x for x in data["signals"] if x["kind"] == "natural_hazard"]) == 1
    assert weighted_context({"AE-DXB": data})[0]["AE-DXB"]["natural_hazards"]
    async def cached(*args, **kwargs):
        return {"AE-DXB": data}
    monkeypatch.setattr("app.services.datapool.context._snapshots_at", cached)
    monkeypatch.setattr(settings, "env", "production")
    async with session_scope() as s:
        source = (await s.execute(select(DataSource).where(DataSource.key == "usgs_earthquakes"))).scalar_one()
        source.licence_approved = False
    assert not (await snapshots_at(["AE-DXB"], now, with_briefs=False))["AE-DXB"]["natural_hazards"]
