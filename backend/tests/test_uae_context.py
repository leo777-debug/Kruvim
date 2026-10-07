"""Synthetic fixture headlines/figures only; external publishers are never called by this suite."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.base import utcnow
from app.db.session import session_scope
from app.models import DataSource, RegionSnapshot, Signal, SourceObservation
from app.services.datapool.base import SignalItem
from app.services.datapool.connectors.environment import CalendarConnector, WeatherConnector
from app.services.datapool.connectors.publisher_rss import geographies, parse_feed
from app.services.datapool.context import snapshots_at
from app.services.datapool.retrieval import personal_match, prepare_retrieval
from app.services.datapool.runner import store_signals
from app.services.llm import ProviderSettings, Usage, make_llm
from app.services.population.generator import generate
from app.services.population.regions import EMIRATE_CONTEXT
from app.services.population.uae import EMIRATES
from app.services.sources import ensure_sources


def test_rss_native_dates_languages_local_matching_and_xml_safety():
    source = SimpleNamespace(key="siraj", name="Fixture Malayalam", status="active", licence_approved=True,
                             reliability=.8, config={"lang": "ml", "feed_url": "https://example.org/feed"})
    raw = ('<rss><channel><item><title>ഷാർജ community fixture</title><link>https://example.org/1</link>'
           '<pubDate>Sun, 04 Oct 2026 08:00:00 GMT</pubDate></item>'
           '<item><title>London fixture</title><link>https://example.org/2</link></item>'
           '<item><title>Dubai undated fixture</title><link>https://example.org/3</link></item></channel></rss>').encode()
    items = parse_feed(raw, source, set(EMIRATES))
    assert len(items) == 1 and items[0].region == "AE-SHJ" and items[0].lang == "ml"
    assert items[0].observed_at == datetime(2026, 10, 4, 8, tzinfo=UTC)
    assert geographies("أبوظبي ودبي fixture") == ["AE-DXB", "AE-AUH"]
    assert geographies("UAE national fixture") == ["AE"]
    assert not geographies("UK fixture")
    with pytest.raises(ValueError, match="safety"):
        parse_feed(b'<!DOCTYPE rss [<!ENTITY x "foo">]><rss/>', source, set(EMIRATES))
    with pytest.raises(ValueError, match="RSS/Atom"):
        parse_feed(b"<html/>", source, set(EMIRATES))


async def test_registered_calendars_native_import_pending_festivals_and_salary_rule():
    async with session_scope() as s:
        await ensure_sources(s)
        source = (await s.execute(select(DataSource).where(DataSource.key == "khda_schools"))).scalar_one()
        source.licence_approved, source.status = True, "active"
        s.add(SourceObservation(source_id=source.id, metric="school_term", dimensions={"name": "Fixture term starts"},
            value=1, unit="event", geography="AE-DXB", raw_ref="asset:fixture", fingerprint="fixture-term", retrieved_at=utcnow(),
            period_start=datetime(2026, 10, 12, tzinfo=UTC), period_end=datetime(2026, 10, 12, 23, 59, tzinfo=UTC)))
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(204))) as client:
        events = await CalendarConnector().fetch(client, EMIRATE_CONTEXT, {}, {"as_of": "2026-10-04"})
    term = [item for item in events if item.title == "Fixture term starts"]
    assert len(term) == 1 and term[0].region == "AE-DXB" and term[0].value == 8
    assert term[0].payload["raw_ref"] == "asset:fixture" and term[0].payload["source_key"] == "khda_schools"
    pending = [item for item in events if item.title.startswith("Onam")]
    assert len(pending) == 4 and all(item.value is None and item.payload["date"] is None for item in pending)
    salary = [item for item in events if item.title.startswith("Month-end")]
    assert len(salary) == 4 and all(item.value == 27 and "estimate, source pending" in item.title for item in salary)


async def test_hourly_emirate_union_retrieval_and_cached_licence_revocation(client, auth, monkeypatch):
    headers, user = auth
    async with session_scope() as s:
        await ensure_sources(s)
        for key in ("siraj", "al_khaleej"):
            source = (await s.execute(select(DataSource).where(DataSource.key == key))).scalar_one()
            source.status, source.licence_approved = "active", True
    items = [SignalItem("headline", "AE-SHJ", "Sharjah fitness fixture", lang="ml", payload={"source_key": "siraj"}),
             SignalItem("headline", "AE-AUH", "Abu Dhabi fitness fixture", lang="ar", payload={"source_key": "al_khaleej"})]
    assert await store_signals("publisher_rss", items) == 2
    assert await store_signals("publisher_rss", items) == 0
    response = await client.get("/datapool/world?regions=AE", headers=headers)
    assert response.status_code == 200, response.text
    snapshots = response.json()
    assert set(snapshots) == {"AE", *EMIRATES}
    assert {item["region"] for item in snapshots["AE"]["news"]} == {"AE-SHJ", "AE-AUH"}
    assert snapshots["AE"]["weather"] is None
    assert "Sharjah" in snapshots["AE"]["brief"] and "Abu Dhabi" in snapshots["AE"]["brief"]
    persona = {"region": "AE", "residence_emirate": "AE-SHJ", "work_emirate": "AE-SHJ", "language": "Malayalam",
               "languages": ["Malayalam", "English"], "nationality_group": "Indian: Kerala/South", "age": 25,
               "platforms": [], "interests": [{"label": "fitness"}]}
    memories, info = await prepare_retrieval(user["orgs"][0]["id"], [persona], {"title": "fitness"}, snapshots,
                                            make_llm(ProviderSettings()), Usage())
    assert memories[0] and {item["region"] for item in memories[0]} == {"AE-SHJ"}
    assert info["provider_calls"] == 0
    async with session_scope() as s:
        archives = (await s.execute(select(RegionSnapshot))).scalars().all()
        assert {row.region for row in archives} == {"AE", *EMIRATES}
        row = (await s.execute(select(DataSource).where(DataSource.key == "siraj"))).scalar_one()
        row.licence_approved = False
        signals = (await s.execute(select(Signal).where(Signal.source == "siraj"))).scalars().all()
        assert all(signal.source_id == row.id for signal in signals)
    monkeypatch.setattr(settings, "env", "production")
    again = (await client.get("/datapool/world?regions=AE", headers=headers)).json()
    assert not again["AE-SHJ"]["news"]
    assert "Sharjah fitness fixture" not in again["AE-SHJ"]["brief"]
    assert not any(item["source"] == "siraj" for item in again["AE"]["signals"])


def test_personal_context_language_community_commute_and_pending_gates():
    person = {"region": "AE", "residence_emirate": "AE-SHJ", "work_emirate": "AE-DXB",
              "nationality_group": "Indian: Kerala/South", "language": "Malayalam", "languages": ["Malayalam", "English"],
              "calendar_memberships": ["Onam"]}
    signal = {"region": "AE-SHJ", "language": "ml", "source_weight": .8}
    assert personal_match(signal, person) > 1
    assert personal_match({**signal, "region": "AE-DXB"}, person) > 0
    assert not personal_match({**signal, "region": "AE-AUH"}, person)
    assert not personal_match({**signal, "language": "ar"}, person)
    assert not personal_match({**signal, "nationality_groups": ["Filipino"]}, person)
    assert not personal_match({**signal, "calendar_membership": "Christmas"}, person)
    assert not personal_match({**signal, "source_weight": 0}, person)


def test_discovery_preview_cannot_bypass_production_weighting_in_graph_or_model_prompts():
    from app.services.datapool.context import weighted_context
    pending = {"source_id": "pending", "source_name": "Pending fixture", "production_eligible": False, "status": "pending_import"}
    approved = {"source_id": "approved", "source_name": "Approved fixture", "production_eligible": True, "status": "active"}
    snapshots = {"AE-SHJ": {"city": "Sharjah", "local_time": "Mon 12:00", "cultural_moment": "Unapproved fixture",
        "signals": [{"source": "pending", "title": "Unapproved fixture", "source_weight": 0, "provenance": pending}],
        "news": [{"source": "approved", "title": "Approved fixture", "source_weight": .5, "provenance": approved}],
        "source_weights": {"pending": 0, "approved": .5}}}
    out, checks = weighted_context(snapshots)
    assert not out["AE-SHJ"]["signals"]
    assert "Unapproved" not in out["AE-SHJ"]["brief"] and "Unapproved" not in out["AE-SHJ"]["cultural_moment"]
    assert "Approved fixture" in out["AE-SHJ"]["brief"]
    assert {item["source_id"] for item in checks} == {"pending", "approved"}


async def test_approved_tone_scorer_does_not_license_pending_upstream_headlines(client):
    from app.services.datapool.context import apply_tone
    from app.services.datapool.tone import select_tone
    at = utcnow()
    async with session_scope() as s:
        await ensure_sources(s)
        scorer = (await s.execute(select(DataSource).where(DataSource.key == "headline_tone"))).scalar_one()
        scorer.status, scorer.licence_approved = "active", True
        s.add(Signal(region="AE-SHJ", source="google_news", kind="headline", title="Fixture peace and growth", observed_at=at, fetched_at=at))
        await s.flush()
        tone = await select_tone(s, "AE-SHJ", at)
        assert tone["avg"] > 0 and tone["provenance"]["production_eligible"] is False
        snapshot = {"region": "AE-SHJ", "signals": [], "freshness": []}
        apply_tone(snapshot, tone)
        assert snapshot["source_weights"]["headline_tone"] == 0


async def test_archive_before_requested_time_has_no_future_or_cross_emirate_leak(client):
    at = utcnow() - timedelta(days=3)
    async with session_scope() as s:
        s.add(RegionSnapshot(region="AE-SHJ", hour=at - timedelta(hours=1), brief="Fixture archived Sharjah", brief_by="template",
            data={"region": "AE-SHJ", "city": "Sharjah", "name": "Sharjah", "local_time": "Mon 12:00", "signals": [], "news": [], "source_weights": {}}))
        s.add(RegionSnapshot(region="AE-SHJ", hour=at + timedelta(hours=1), brief="Future fixture", brief_by="template", data={}))
    out = await snapshots_at(["AE"], at, with_briefs=False)
    assert out["AE-SHJ"]["brief"] == "Fixture archived Sharjah" and out["AE-SHJ"]["archived"]
    assert out["AE-AUH"]["archive_missing"] and "Future fixture" not in out["AE"]["brief"]


async def test_weather_uses_distinct_registered_coordinates_and_northern_proxy():
    seen = set()
    def handle(request):
        seen.add((request.url.params["latitude"], request.url.params["longitude"]))
        return httpx.Response(200, json={"current": {"temperature_2m": 20, "apparent_temperature": 21, "weather_code": 0}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        items = await WeatherConnector().fetch(client, EMIRATE_CONTEXT, {}, {})
    assert len(seen) == len(items) == 4
    assert all(item.payload["coordinate_source"] == "open_meteo_geocoding" for item in items)
    assert [item.region for item in items if item.payload["weather_proxy"]] == ["AE-NE"]


def test_optional_visitor_stock_layer_defaults_excluded_and_is_deterministic():
    priors = {"_uae_targets": [{"geography": "AE", "dimensions": {"status": "visitor"}, "fraction": .1}]}
    a, b = generate(10000, 42, priors), generate(10000, 42, priors)
    np.testing.assert_array_equal(a.uae["status"], b.uae["status"])
    all_ae = a.mask({"regions": ["AE"], "include_visitors": True})
    residents = a.mask({"regions": ["AE"]})
    assert (all_ae & ~residents).sum() > 0
    assert np.mean(a.uae["status"][all_ae] == 1) == pytest.approx(.1, abs=.02)
    assert not generate(10000, 42).uae["status"].any()


def test_native_scalar_attributes_and_missing_period_denominator_are_not_invented():
    from app.services.population.uae import reconcile
    source = SimpleNamespace(id="fixture", name="Fixture", publisher="Fixture", url="https://example.org", attribution="Fixture",
        geography_level="country", reliability=.9, status="active", licence_approved=True, config={})
    start, end = datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 12, 31, tzinfo=UTC)
    def cell(id_, metric, value, dimensions, unit="fraction", period_start=start):
        return SimpleNamespace(id=id_, source_id="fixture", metric=metric, value=value, dimensions=dimensions,
            unit=unit, period_start=period_start, period_end=end, geography="AE")
    targets, provenance = reconcile([cell("r", "remittance_share", .25, {"nationality_group": "Filipino"}),
        cell("p", "platform_share", 1, {"platform": "whatsapp"}), cell("s", "salary_day", 28, {}, "day"),
        cell("t", "population_total", 100, {}, "persons"),
        cell("m", "population_count", 80, {"sex": "male"}, "persons", datetime(2025, 6, 1, tzinfo=UTC))], {"fixture": source}, datetime(2026, 1, 1, tzinfo=UTC))
    assert not any(t["observation_id"] == "m" for t in targets)  # Equal period end is not enough to establish a denominator.
    pop = generate(10000, 42, {"_uae_targets": targets, "_provenance": provenance})
    ae = pop.region == 0
    assert pop.uae["whatsapp"][ae].all() and (pop.uae["salary_day"][ae] == 28).all()
    group = ae & (pop.uae["nationality_group"] == 6)
    assert np.allclose(pop.uae["remittance_share"][group], .25)
    assert np.isnan(pop.uae["remittance_share"][ae & ~group]).all()
