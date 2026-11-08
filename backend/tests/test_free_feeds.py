"""Synthetic GDELT records verify the free collection and simulation path."""
import io
import zipfile
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.config import settings
from app.services.datapool import REGISTRY
from app.services.datapool.connectors.free_news import BASE_URL, GdeltEventsConnector, parse_events
from app.services.datapool.context import build_snapshot_data
from app.services.datapool.runner import refresh_free_feeds, store_signals

REGIONS = [{"code": "AE-DXB", "country": "AE", "gdelt_country": "unitedarabemirates"},
           {"code": "AE-AUH", "country": "AE", "gdelt_country": "unitedarabemirates"},
           {"code": "GB", "gdelt_country": "unitedkingdom"}, {"code": "MA", "gdelt_country": "morocco"}]


def record(now, **changes):
    row = [""] * 61
    values = {0: "12345", 1: now.strftime("%Y%m%d"), 6: "SYNTHETIC ACTOR", 16: "SYNTHETIC COUNTERPART",
              26: "040", 28: "04", 52: "Dubai, United Arab Emirates", 53: "AE",
              59: now.strftime("%Y%m%d%H%M%S"), 60: "https://example.org/source-report"}
    values.update({int(key): value for key, value in changes.items()})
    for key, value in values.items():
        row[key] = value
    return row


def zipped(rows):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("events.CSV", "\n".join("\t".join(row) for row in rows))
    return buffer.getvalue()


async def test_public_bulk_request_dates_geography_attribution_and_duplicates():
    now = datetime.now(UTC) - timedelta(minutes=1)
    row = record(now)
    calls = []
    def response(request):
        calls.append(request)
        if request.url.path.endswith("lastupdate.txt"):
            return httpx.Response(200, text=f"200 checksum http://data.gdeltproject.org/gdeltv2/{now:%Y%m%d%H%M%S}.export.CSV.zip\n")
        return httpx.Response(200, content=zipped([row, row]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        items = await GdeltEventsConnector().fetch(client, REGIONS, {}, {})
    assert len(calls) == 5 and len(items) == 1
    assert all(str(request.url).startswith(BASE_URL) for request in calls)
    assert all("authorization" not in request.headers for request in calls)
    item = items[0]
    assert item.region == "AE-DXB" and item.url == row[60]
    assert item.payload["timestamp_kind"] == "GDELT ingestion time"
    assert item.payload["dataset_url"] == "https://www.gdeltproject.org/"
    assert item.observed_at == now.replace(microsecond=0)
    assert "consultation" in item.title and "coded report" in item.title


def test_country_events_are_shared_with_matching_emirates_and_bad_records_are_skipped():
    now = datetime.now(UTC)
    national = record(now, **{"52": "United Arab Emirates"})
    items = parse_events(zipped([national]), REGIONS, now)
    assert {item.region for item in items} == {"AE-DXB", "AE-AUH"}
    assert all(item.payload["geography_match"] == "country" for item in items)
    britain = record(now, **{"53": "UK", "52": "London, United Kingdom"})
    morocco = record(now, **{"53": "MO", "52": "Casablanca, Morocco"})
    assert {item.region for item in parse_events(zipped([britain, morocco]), REGIONS, now)} == {"GB", "MA"}
    bad = [record(now, **{"1": "20200101"}), record(now + timedelta(hours=1)),
           record(now, **{"60": "javascript:alert(1)"}), record(now, **{"28": "99"}), ["invalid"]]
    assert parse_events(zipped(bad), REGIONS, now) == []
    with pytest.raises(ValueError, match="5 MB"):
        parse_events(b"x" * (5 * 1024 * 1024 + 1), REGIONS, now)


async def test_stale_index_does_not_create_fresh_events():
    old = datetime.now(UTC) - timedelta(days=2)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, text=f"{old:%Y%m%d%H%M%S}.export.CSV.zip"))) as client:
        with pytest.raises(ValueError, match="stale"):
            await GdeltEventsConnector().fetch(client, REGIONS, {}, {})


async def test_announced_future_batch_uses_a_completed_batch():
    now = datetime.now(UTC)
    announced = now.replace(second=0, microsecond=0) + timedelta(minutes=10)
    calls = []
    def response(request):
        calls.append(request)
        if request.url.path.endswith("lastupdate.txt"):
            return httpx.Response(200, text=f"{announced:%Y%m%d%H%M%S}.export.CSV.zip")
        return httpx.Response(200, content=zipped([record(now - timedelta(minutes=5))]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        items = await GdeltEventsConnector().fetch(client, REGIONS, {}, {})
    assert items and items[0].observed_at <= now
    assert calls[1].url.path.endswith(f"{announced-timedelta(minutes=15):%Y%m%d%H%M%S}.export.CSV.zip")


async def test_missing_newest_batch_uses_earlier_exports_and_all_missing_is_an_error():
    now = datetime.now(UTC) - timedelta(minutes=1)
    latest = f"{now:%Y%m%d%H%M%S}.export.CSV.zip"
    def response(request):
        if request.url.path.endswith("lastupdate.txt"):
            return httpx.Response(200, text=latest)
        if request.url.path.endswith(latest):
            return httpx.Response(404)
        return httpx.Response(200, content=zipped([record(now)]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        assert await GdeltEventsConnector().fetch(client, REGIONS, {}, {})
    def missing(request):
        return httpx.Response(200, text=latest) if request.url.path.endswith("lastupdate.txt") else httpx.Response(404)
    async with httpx.AsyncClient(transport=httpx.MockTransport(missing)) as client:
        with pytest.raises(ValueError, match="unavailable"):
            await GdeltEventsConnector().fetch(client, REGIONS, {}, {})


async def test_free_records_reach_simulation_snapshot_and_deduplicate(monkeypatch):
    now = datetime.now(UTC)
    items = parse_events(zipped([record(now)]), REGIONS, now)
    monkeypatch.setattr(settings, "env", "production")
    assert await store_signals("gdelt_events", items) == 1
    assert await store_signals("gdelt_events", items) == 0
    snapshot = await build_snapshot_data("AE-DXB", datetime.now(UTC))
    news = next(item for item in snapshot["news"] if item["source"] == "gdelt_events")
    assert news["provenance"]["production_eligible"]
    assert news["url"] == "https://example.org/source-report"
    assert "GDELT" in news["title"]


async def test_hosted_refresh_claims_only_free_sources_once(monkeypatch):
    run = AsyncMock(return_value={"status": "ok", "items": 1})
    monkeypatch.setattr("app.services.datapool.runner.run_connector", run)
    assert len(await refresh_free_feeds()) == 4
    assert await refresh_free_feeds() == []
    assert [call.args[0] for call in run.await_args_list] == ["gdelt_events", "usgs_earthquakes", "nasa_eonet", "wikipedia"]
    assert "world_monitor" not in REGISTRY
    assert all(not REGISTRY[key].spec.secrets for key in ("gdelt_events", "usgs_earthquakes", "nasa_eonet"))
