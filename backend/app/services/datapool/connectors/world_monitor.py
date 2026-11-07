"""Authenticated World Monitor country headlines with publisher dates and attribution."""
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from ..base import BaseConnector, ConnectorSpec, SignalItem
from .hazards import timestamp
from .publisher_rss import geographies

HEADLINES_URL = "https://api.worldmonitor.app/api/news/v1/list-country-headlines"


class WorldMonitorConnector(BaseConnector):
    spec = ConnectorSpec(
        "world_monitor", "World Monitor news", "news",
        "Dated country headlines from the World Monitor API, with original publisher links.",
        secrets=["world_monitor_api_key"], interval_minutes=60,
        license_note="Requires World Monitor API access covering customer-facing use and retained simulation evidence. "
                     "Record the applicable agreement in Sources before activation.",
        docs_url="https://www.worldmonitor.app/developers.md",
    )

    async def fetch(self, client, regions, secrets, config):
        self.need(secrets)
        countries = sorted({r.get("country", r["code"]).split("-")[0] for r in regions})
        if not countries:
            return []
        response = await client.get(HEADLINES_URL,
            params=[("country_codes", country) for country in countries],
            headers={"X-WorldMonitor-Key": secrets["world_monitor_api_key"]},
            follow_redirects=False)
        response.raise_for_status()
        if len(response.content) > 2 * 1024 * 1024:
            raise ValueError("World Monitor response exceeds 2 MB")
        data = response.json()
        if not isinstance(data, dict) or data.get("state") not in {"complete", "partial"}:
            raise ValueError("World Monitor country news is unavailable")
        buckets = data.get("countries")
        if not isinstance(buckets, dict):
            raise ValueError("World Monitor response has no country buckets")
        now, out, seen = datetime.now(UTC), [], set()
        for country in countries:
            bucket = buckets.get(country, {})
            if not isinstance(bucket, dict) or not isinstance(bucket.get("items", []), list):
                raise ValueError("World Monitor country bucket is malformed")
            for article in bucket.get("items", [])[:5]:
                if not isinstance(article, dict):
                    continue
                title, publisher, link = (article.get(k) for k in ("title", "source", "link"))
                if not all(isinstance(v, str) and v.strip() for v in (title, publisher, link)):
                    continue
                try:
                    parsed = urlparse(link)
                except ValueError:
                    continue
                published = article.get("publishedAt")
                # Protobuf int64 values may be JSON numbers or decimal strings.
                if isinstance(published, str) and published.isdecimal():
                    published = int(published)
                observed = timestamp(published)
                if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                        or observed is None or not now - timedelta(hours=24) <= observed <= now):
                    continue
                local = geographies(title) if country == "AE" else []
                for region in regions:
                    code = region["code"]
                    if region.get("country", code).split("-")[0] != country:
                        continue
                    if local and local != ["AE"] and code not in local:
                        continue
                    if (code, link) in seen:
                        continue
                    seen.add((code, link))
                    out.append(SignalItem("headline", code, f"{title.strip()[:200]} — {publisher.strip()[:100]}",
                        url=link, observed_at=observed,
                        payload={"collector": "world_monitor", "publisher": publisher.strip()[:100],
                            "country": country, "geography_match": "headline" if local and local != ["AE"] else "country",
                            "coverage_state": data["state"], "source_url": link}))
        return out


async def refresh_due():
    """Claim the hosted hourly check before making one request for all countries."""
    from sqlalchemy import select

    from app.db.base import utcnow
    from app.db.session import session_scope
    from app.models import Connector
    from app.services.datapool.runner import ensure_platform_connectors, run_connector

    await ensure_platform_connectors()
    async with session_scope() as session:
        row = (await session.execute(select(Connector).where(Connector.key == "world_monitor",
            Connector.org_id.is_(None)).with_for_update(skip_locked=True))).scalar_one_or_none()
        now = utcnow()
        if not row or not row.enabled or not row.interval_minutes:
            return {"status": "disabled"}
        if row.last_run_at and row.last_run_at + timedelta(minutes=row.interval_minutes) > now:
            return {"status": "not_due"}
        row.last_run_at = now
    return await run_connector("world_monitor")
