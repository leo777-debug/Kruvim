from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from app.db.session import session_scope
from app.models import RegionSnapshot
from app.services.datapool.context import hour_bucket, refresh_snapshot_archive, saved_snapshots
from app.services.population.regions import CONTEXT_CODES, region


def test_mistral_keeps_its_provider_identity_with_openai_compatible_transport():
    from app.services.llm import ProviderSettings
    from app.services.llm.errors import classify
    issue = classify(429, {"message": "Too many requests"}, settings=ProviderSettings(
        provider="openai", preset="mistral", base_url="https://api.mistral.ai/v1"))
    assert issue.provider == "mistral" and issue.category == "rate_limited"


async def test_region_browsing_never_collects_or_calls_a_model(client, auth, monkeypatch):
    collect = AsyncMock(side_effect=AssertionError("dashboard must not collect upstreams"))
    resolve = AsyncMock(side_effect=AssertionError("dashboard must not resolve a model"))
    monkeypatch.setattr("app.services.datapool.context.ensure_fresh", collect)
    monkeypatch.setattr("app.services.providers.resolve", resolve)
    headers, _ = auth
    response = await client.get("/datapool/world?regions=AE-DXB", headers=headers)
    assert response.status_code == 200
    data = response.json()["AE-DXB"]
    assert data["data_status"] == "unavailable"
    assert data["city"] == "Dubai"
    assert data["snapshot_at"] is None
    collect.assert_not_awaited()
    resolve.assert_not_awaited()


async def test_preview_uses_latest_saved_snapshot_before_cutoff():
    now = datetime.now(UTC)
    bucket = hour_bucket(now)
    base = {"region": "AE-DXB", "city": "Dubai", "name": "Dubai", "local_time": "Sun 10:00", "signals": []}
    async with session_scope() as session:
        session.add_all([
            RegionSnapshot(region="AE-DXB", hour=bucket - timedelta(hours=1), data=base, brief="Synthetic saved older context.", brief_by="template"),
            RegionSnapshot(region="AE-DXB", hour=bucket, data=base, brief="Synthetic latest saved context.", brief_by="template"),
            RegionSnapshot(region="AE-DXB", hour=bucket + timedelta(hours=1), data=base, brief="Synthetic future context.", brief_by="template"),
        ])
    data = await saved_snapshots(["AE-DXB", "GB"], now)
    assert data["AE-DXB"]["brief"] == "Synthetic latest saved context."
    assert data["AE-DXB"]["data_status"] == "ready"
    assert data["GB"]["data_status"] == "unavailable"
    earlier = await saved_snapshots(["AE-DXB"], bucket - timedelta(minutes=1))
    assert earlier["AE-DXB"]["brief"] == "Synthetic saved older context."


async def test_scheduler_publishes_hour_once_without_upstream_fetches(monkeypatch):
    async def build(code, at):
        reg = region(code)
        return {"region": code, "city": reg["city"], "name": reg["name"], "local_time": "Sun 10:00", "signals": []}
    collect = AsyncMock(side_effect=AssertionError("collector is a separate scheduled step"))
    monkeypatch.setattr("app.services.datapool.context.ensure_fresh", collect)
    monkeypatch.setattr("app.services.datapool.context.build_snapshot_data", build)
    assert await refresh_snapshot_archive() == len(CONTEXT_CODES)
    assert await refresh_snapshot_archive() == 0
    assert all(item["data_status"] == "ready" for item in (await saved_snapshots(CONTEXT_CODES, datetime.now(UTC))).values())
    collect.assert_not_awaited()
