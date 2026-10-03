"""News and attention: Google News RSS headlines, GDELT news tone, Wikipedia most-read pages."""
from __future__ import annotations

import asyncio
import datetime as dt
import html
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from ..base import BaseConnector, ConnectorSpec, SignalItem


class GoogleNewsConnector(BaseConnector):
    spec = ConnectorSpec("google_news", "Google News headlines", "news", "Top stories per regional edition (RSS).",
                         interval_minutes=30, supports_search=True,
                         license_note="RSS for personal/non-commercial use; license a news API for commercial scale.",
                         docs_url="https://news.google.com/")

    @staticmethod
    def _parse(content: bytes, region: str, limit: int = 15) -> list[SignalItem]:
        root = ET.fromstring(content)
        out = []
        for item in root.iter("item"):
            title = html.unescape(item.findtext("title") or "").strip()
            src = item.find("source")
            source = src.text.strip() if src is not None and src.text else ""
            if source and title.endswith(" - " + source):
                title = title[: -(len(source) + 3)]
            try:
                when = parsedate_to_datetime(item.findtext("pubDate") or "")
            except Exception:
                when = None
            out.append(SignalItem("headline", region, title, url=item.findtext("link"), observed_at=when,
                                  payload={"source": source}))
            if len(out) >= limit:
                break
        return out

    async def fetch(self, client, regions, secrets, config):
        async def one(reg):
            r = await client.get(reg["news_rss"])
            r.raise_for_status()
            items = self._parse(r.content, reg["code"])
            for i in items:
                i.lang = reg["lang_code"]
            return items
        res = await asyncio.gather(*[one(r) for r in regions], return_exceptions=True)
        return [x for lst in res if isinstance(lst, list) for x in lst]

    async def search(self, client, query, regions, secrets, config, limit=10):
        reg = regions[0] if regions else {"code": "*", "lang_code": "en"}
        lang = "ar" if reg.get("lang_code") == "ar" else "en"
        r = await client.get("https://news.google.com/rss/search", params={"q": query, "hl": lang, "gl": "US", "ceid": f"US:{lang}"})
        r.raise_for_status()
        items = self._parse(r.content, reg["code"], limit)
        for i in items:
            i.kind = "news_mention"
        return items


class RegionalTrendsConnector(BaseConnector):
    spec = ConnectorSpec("regional_trends", "Regional search trends", "social", "Country-specific trending searches from Google Trends RSS.",
                         interval_minutes=60, docs_url="https://trends.google.com/trending")

    async def fetch(self, client, regions, secrets, config):
        async def one(reg):
            response = await client.get("https://trends.google.com/trending/rss", params={"geo": reg["code"]})
            response.raise_for_status()
            out = []
            for item in ET.fromstring(response.content).iter("item"):
                title = (item.findtext("title") or "").strip()
                traffic = next((x.text or "" for x in item if x.tag.endswith("approx_traffic")), "")
                match = re.search(r"([\d,.]+)\s*([KM]?)", traffic.upper())
                value = float(match[1].replace(",", "")) * {"K": 1000, "M": 1000000, "": 1}[match[2]] if match else None
                if title:
                    out.append(SignalItem("social_trend", reg["code"], title, value=value, url=item.findtext("link"),
                        payload={"platform": "google_trends", "country": reg["code"], "measurement": "search traffic", "source": "country RSS"}))
            return out[:12]
        results = await asyncio.gather(*(one(r) for r in regions), return_exceptions=True)
        return [item for result in results if isinstance(result, list) for item in result]


_gdelt_lock = asyncio.Lock()
_gdelt_state = {"last": 0.0, "blocked_until": 0.0}


class GdeltToneConnector(BaseConnector):
    spec = ConnectorSpec("gdelt", "GDELT news tone", "tone", "Average tone of local news coverage over 24 hours.",
                         interval_minutes=120, license_note="Free; rate-limited to one request every 5 seconds.",
                         docs_url="https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/")

    async def fetch(self, client, regions, secrets, config):
        out = []
        for reg in regions:
            if time.time() < _gdelt_state["blocked_until"]:
                break
            async with _gdelt_lock:
                wait = 5.5 - (time.time() - _gdelt_state["last"])
                if wait > 0:
                    await asyncio.sleep(wait)
                _gdelt_state["last"] = time.time()
                try:
                    r = await client.get("https://api.gdeltproject.org/api/v2/doc/doc", params={
                        "query": f"sourcecountry:{reg['gdelt_country']}", "mode": "tonechart", "format": "json", "timespan": "24h"})
                except Exception:
                    continue
            if r.status_code == 429:
                _gdelt_state["blocked_until"] = time.time() + 600
                break
            if r.status_code != 200:
                continue
            try:
                bins = r.json().get("tonechart") or []
            except Exception:
                continue
            n = sum(b.get("count", 0) for b in bins)
            if not n:
                continue
            avg = sum(b["bin"] * b["count"] for b in bins) / n
            neg = sum(b["count"] for b in bins if b["bin"] <= -5) / n
            out.append(SignalItem("tone", reg["code"], f"News tone {avg:+.1f} ({n} articles)", value=round(avg, 2),
                                  payload={"articles": n, "share_very_negative": round(neg, 3)}))
        if not out and time.time() < _gdelt_state["blocked_until"]:
            raise RuntimeError("GDELT is rate-limiting this server; will retry later")
        return out


_WIKI_SKIP = re.compile(r"^(Main_Page|Special:|Wikipedia:|Portal:|File:|Help:|Category:|خاص:|ملف:|تصنيف:|بوابة:|الصفحة_الرئيسة|"
                        r"ويكيبيديا:|Spécial:|Fichier:|Catégorie:|Accueil|Wikipédia:|मुखपृष्ठ|विशेष:|चित्र:|श्रेणी:)|"
                        r"\.(jpe?g|png|gif|svg|webm|ogv)$", re.I)


class WikipediaConnector(BaseConnector):
    spec = ConnectorSpec("wikipedia", "Wikipedia attention", "attention", "Most-read pages yesterday per language edition.",
                         interval_minutes=360, supports_search=True, docs_url="https://wikimedia.org/api/rest_v1/")

    async def safe_pages(self, client, lang, titles):
        from ..safety import safe_title
        titles = [t for t in titles if safe_title(t)]
        if not titles:
            return set()
        response = await client.get(f"https://{lang}.wikipedia.org/w/api.php", params={"action": "query", "prop": "categories",
            "titles": "|".join(titles), "cllimit": "max", "redirects": 1, "format": "json"})
        response.raise_for_status()
        data = response.json().get("query", {})
        safe = {p["title"].replace("_", " ") for p in data.get("pages", {}).values()
                if "missing" not in p and safe_title(p["title"], [c["title"] for c in p.get("categories", [])])}
        aliases = {x["from"].replace("_", " "): x["to"].replace("_", " ") for x in data.get("normalized", []) + data.get("redirects", [])}
        return {t for t in titles if aliases.get(t.replace("_", " "), t.replace("_", " ")) in safe}

    async def search(self, client, query, regions, secrets, config, limit=10):
        out = []
        for reg in regions[:3]:
            lang = reg["wiki_lang"]
            r = await client.get(f"https://{lang}.wikipedia.org/w/api.php", params={"action": "query", "list": "search",
                "srsearch": query[:300], "srlimit": min(limit, 10), "format": "json"})
            r.raise_for_status()
            items = r.json().get("query", {}).get("search", [])
            allowed = await self.safe_pages(client, lang, [x["title"] for x in items])
            for item in items:
                if item["title"] not in allowed:
                    continue
                title = item["title"]
                out.append(SignalItem("trend", reg["code"], title, url=f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}",
                    payload={"summary": html.unescape(re.sub(r"<[^>]+>", "", item.get("snippet", "")))[:500], "source": "wikipedia"}))
        return out

    async def fetch(self, client, regions, secrets, config):
        by_lang: dict[str, list[dict]] = {}
        for reg in regions:
            by_lang.setdefault(reg["wiki_lang"], []).append(reg)
        out = []
        for lang, regs in by_lang.items():
            for back in (1, 2):
                d = dt.datetime.now(dt.UTC) - dt.timedelta(days=back)
                r = await client.get(f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/{lang}.wikipedia/all-access/{d:%Y}/{d:%m}/{d:%d}")
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                arts = [a for a in r.json()["items"][0]["articles"] if not _WIKI_SKIP.search(a["article"])][:12]
                allowed = await self.safe_pages(client, lang, [a["article"] for a in arts])
                arts = [a for a in arts if a["article"] in allowed]
                for reg in regs:
                    for a in arts:
                        out.append(SignalItem("trend", reg["code"], a["article"].replace("_", " "), value=float(a["views"]),
                                              lang=lang, url=f"https://{lang}.wikipedia.org/wiki/{a['article']}",
                                              payload={"date": f"{d:%Y-%m-%d}", "source": "wikipedia"}))
                break
        return out
