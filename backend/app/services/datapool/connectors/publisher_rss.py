"""Only publisher RSS/Atom metadata; no article-page scraping and no invented regional coverage."""
from __future__ import annotations

import asyncio
import html
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from sqlalchemy import select

from app.core.config import settings
from app.db.session import session_scope
from app.models import DataSource
from app.services.population.uae import EMIRATES
from app.services.sources import eligible, ensure_sources
from app.services.sources.adapters import public_url

from ..base import BaseConnector, ConnectorSpec, SignalItem

MARKERS = {"AE-DXB": ["dubai", "دبي", "ദുബൈ", "ദുബായ്"], "AE-AUH": ["abu dhabi", "abudhabi", "أبوظبي", "ابوظبي", "أبو ظبي", "അബൂദബി", "അബുദാബി", "al ain", "العين"],
           "AE-SHJ": ["sharjah", "الشارقة", "شارقة", "ഷാർജ", "ഷാര്‍ജ"],
           "AE-NE": ["ajman", "عجمان", "ras al khaimah", "ras al-khaimah", "رأس الخيمة", "راس الخيمة", "fujairah", "الفجيرة", "umm al quwain", "أم القيوين"]}


def geographies(text):
    text = text.casefold()
    found = [code for code, markers in MARKERS.items() if any(marker in text for marker in markers)]
    if not found and any(marker in text for marker in ("uae", "united arab emirates", "الإمارات", "الامارات", "യു.എ.ഇ", "യുഎഇ")):
        found = ["AE"]
    return found


def parse_feed(raw, source, allowed):
    if len(raw) > 2 * 1024 * 1024 or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("Feed exceeds XML safety limits")
    root = ET.fromstring(raw)
    if root.tag.rsplit("}", 1)[-1] not in ("rss", "feed", "RDF"):
        raise ValueError("Publisher endpoint did not return an RSS/Atom feed")
    out = []
    elements = root.findall(".//item") or root.findall("{http://www.w3.org/2005/Atom}entry")
    for item in elements[:100]:
        values = {child.tag.rsplit("}", 1)[-1]: child for child in item}
        def value(key, fields=values):
            child = fields.get(key)
            return child.text if child is not None and child.text else ""
        title = html.unescape(re.sub(r"<[^>]*>", "", value("title"))).strip()[:500]
        link = value("link") or (values["link"].get("href", "") if "link" in values else "")
        if not title or urlparse(link).scheme not in ("https", "http"):
            continue
        when = None
        raw_date = value("pubDate") or value("published") or value("updated")
        if raw_date:
            try:
                when = parsedate_to_datetime(raw_date)
            except (ValueError, TypeError):
                try:
                    when = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                except ValueError:
                    continue  # Undecodable dates never become falsely fresh articles.
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
        else:
            continue  # Publication time is required for hourly context; retrieval time is not a substitute.
        scope = geographies(title)
        for code in scope:
            if code not in allowed:
                continue
            out.append(SignalItem("headline", code, title, url=link, lang=source.config.get("lang", "en"), observed_at=when,
                payload={"source": source.name, "source_key": source.key, "feed_url": source.config["feed_url"],
                         "emirate": code, "nationality_groups": ["Filipino"] if source.key == "filipino_times" else [],
                         "date_status": "publisher" if when else "undated", "status": "active" if eligible(source) else "pending_import"}))
    return out


class PublisherRssConnector(BaseConnector):
    spec = ConnectorSpec("publisher_rss", "Registered UAE publisher feeds", "news", "Arabic, English and community headlines matched to emirates; registered licences govern production use.",
                         interval_minutes=60, docs_url="https://www.alkhaleej.ae/rss")

    async def fetch(self, client, regions, secrets, config):
        async with session_scope() as s:
            await ensure_sources(s)
            sources = (await s.execute(select(DataSource).where(DataSource.status != "deprecated"))).scalars().all()
        sources = [r for r in sources if r.config.get("adapter") == "rss" and r.config.get("feed_url")
                   and (settings.env != "production" or eligible(r))]
        allowed = {r["code"] for r in regions}
        if "AE" in allowed:
            allowed.update(EMIRATES)
        async def one(source):
            await public_url(source.config["feed_url"])
            async with client.stream("GET", source.config["feed_url"], follow_redirects=False) as response:
                response.raise_for_status()
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 2 * 1024 * 1024:
                        raise ValueError("Publisher RSS exceeds 2 MB")
                    chunks.append(chunk)
            return parse_feed(b"".join(chunks), source, allowed)
        results = await asyncio.gather(*(one(r) for r in sources), return_exceptions=True)
        import logging
        for source, result in zip(sources, results, strict=True):
            if isinstance(result, Exception):
                logging.getLogger("kruvim.datapool").warning("Publisher feed unavailable: %s (%s)", source.key, type(result).__name__)
        return [item for result in results if isinstance(result, list) for item in result]
