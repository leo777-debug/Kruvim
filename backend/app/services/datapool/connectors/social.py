"""Social platforms. Keyless: Mastodon trends, Bluesky trending topics. With credentials: Reddit,
YouTube, X, Bluesky search. Each social connector can also *listen*: return live posts about a
topic so simulations start from the real conversation happening right now."""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime

from ..base import BaseConnector, ConnectorSpec, SignalItem

_TAG = re.compile(r"<[^>]+>")

REGIONAL_TERMS = {"AE": ["dubai", "uae", "emirates", "دبي", "الإمارات"], "SA": ["saudi", "riyadh", "jeddah", "السعودية", "الرياض"],
                  "EG": ["egypt", "cairo", "مصر", "القاهرة"], "JO": ["jordan", "amman", "الأردن", "عمان"],
                  "MA": ["morocco", "casablanca", "المغرب"], "US": ["united states", "american", "usa"],
                  "GB": ["united kingdom", "britain", "london", "british"], "IN": ["india", "mumbai", "indian", "भारत"]}


def regionalize(items, regions):
    """A global social service is not a country's trend feed. Keep explicit geographic evidence only."""
    from dataclasses import replace
    return [replace(item, region=reg["code"]) for reg in regions for item in items
            if any(term in item.title.casefold() for term in REGIONAL_TERMS.get(reg["code"], []))]


def _iso(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


class MastodonConnector(BaseConnector):
    spec = ConnectorSpec("mastodon", "Mastodon trends", "social", "Trending hashtags and links on mastodon.social; hashtag listening.",
                         interval_minutes=60, supports_search=True, docs_url="https://docs.joinmastodon.org/methods/trends/")
    BASE = "https://mastodon.social"

    async def fetch(self, client, regions, secrets, config):
        base = config.get("instance") or self.BASE
        tags = (await client.get(f"{base}/api/v1/trends/tags", params={"limit": 10})).json()
        links = (await client.get(f"{base}/api/v1/trends/links", params={"limit": 8})).json()
        out = []
        for t in tags:
            uses = sum(int(h.get("uses", 0)) for h in (t.get("history") or [])[:2])
            out.append(SignalItem("social_trend", "*", "#" + t["name"], value=float(uses), url=t.get("url"),
                                  payload={"platform": "mastodon", "type": "hashtag"}))
        for link in links:
            out.append(SignalItem("social_trend", "*", link.get("title") or link.get("url"), url=link.get("url"),
                                  value=float(sum(int(h.get("uses", 0)) for h in (link.get("history") or [])[:2])),
                                  payload={"platform": "mastodon", "type": "link", "provider": link.get("provider_name")}))
        return regionalize(out, regions)

    async def search(self, client, query, regions, secrets, config, limit=10):
        base = config.get("instance") or self.BASE
        tag = re.sub(r"[^\w]", "", query.split()[0]) if query.split() else ""
        if not tag:
            return []
        r = await client.get(f"{base}/api/v1/timelines/tag/{tag}", params={"limit": limit})
        if r.status_code != 200:
            return []
        out = []
        for s in r.json():
            text = _TAG.sub(" ", s.get("content") or "").strip()
            if text:
                out.append(SignalItem("social_post", "*", text[:500], url=s.get("url"), lang=s.get("language"),
                                      observed_at=_iso(s.get("created_at")),
                                      value=float((s.get("favourites_count") or 0) + (s.get("reblogs_count") or 0)),
                                      payload={"platform": "mastodon", "author": (s.get("account") or {}).get("acct", "")}))
        return out


class BlueskyConnector(BaseConnector):
    spec = ConnectorSpec("bluesky", "Bluesky", "social", "Trending topics (keyless); post search needs a handle + app password.",
                         interval_minutes=60, supports_search=True, docs_url="https://docs.bsky.app/")
    _session: dict = {}

    async def fetch(self, client, regions, secrets, config):
        r = await client.get("https://public.api.bsky.app/xrpc/app.bsky.unspecced.getTrendingTopics", params={"limit": 12})
        r.raise_for_status()
        data = r.json()
        out = []
        for t in (data.get("topics") or []) + (data.get("suggested") or [])[:5]:
            title = t.get("displayName") or t.get("topic") or ""
            if title:
                out.append(SignalItem("social_trend", "*", title, url="https://bsky.app" + (t.get("link") or ""),
                                      payload={"platform": "bluesky", "description": t.get("description")}))
        return regionalize(out, regions)

    async def _token(self, client, secrets):
        cached = self._session.get(secrets.get("bluesky_handle"))
        if cached and cached[1] > time.time():
            return cached[0]
        r = await client.post("https://bsky.social/xrpc/com.atproto.server.createSession",
                               json={"identifier": secrets["bluesky_handle"], "password": secrets["bluesky_app_password"]})
        r.raise_for_status()
        tok = r.json()["accessJwt"]
        self._session[secrets["bluesky_handle"]] = (tok, time.time() + 3000)
        return tok

    async def search(self, client, query, regions, secrets, config, limit=10):
        if not (secrets.get("bluesky_handle") and secrets.get("bluesky_app_password")):
            return []
        tok = await self._token(client, secrets)
        r = await client.get("https://bsky.social/xrpc/app.bsky.feed.searchPosts", params={"q": query, "limit": limit, "sort": "latest"},
                             headers={"Authorization": f"Bearer {tok}"})
        r.raise_for_status()
        out = []
        for p in r.json().get("posts", []):
            rec = p.get("record") or {}
            out.append(SignalItem("social_post", "*", (rec.get("text") or "")[:500], lang=(rec.get("langs") or [None])[0],
                                  observed_at=_iso(rec.get("createdAt")),
                                  value=float((p.get("likeCount") or 0) + (p.get("repostCount") or 0)),
                                  url=f"https://bsky.app/profile/{(p.get('author') or {}).get('handle')}",
                                  payload={"platform": "bluesky", "author": (p.get("author") or {}).get("handle", "")}))
        return out


class RedditConnector(BaseConnector):
    spec = ConnectorSpec("reddit", "Reddit", "social", "Hot threads in regional subreddits; topic search.",
                         secrets=["reddit_client_id", "reddit_client_secret"], interval_minutes=60, supports_search=True,
                         license_note="Commercial use requires Reddit's paid Data API terms.",
                         docs_url="https://www.reddit.com/dev/api/")
    _tok: dict = {}

    async def _token(self, client, secrets):
        cid = secrets["reddit_client_id"]
        cached = self._tok.get(cid)
        if cached and cached[1] > time.time():
            return cached[0]
        r = await client.post("https://www.reddit.com/api/v1/access_token", data={"grant_type": "client_credentials"},
                              auth=(cid, secrets["reddit_client_secret"]))
        r.raise_for_status()
        d = r.json()
        self._tok[cid] = (d["access_token"], time.time() + int(d.get("expires_in", 3600)) - 60)
        return d["access_token"]

    def _items(self, children, region, kind):
        out = []
        for c in children:
            d = c.get("data") or {}
            out.append(SignalItem(kind, region, (d.get("title") or "")[:400], value=float(d.get("score") or 0),
                                  url="https://reddit.com" + (d.get("permalink") or ""),
                                  observed_at=datetime.fromtimestamp(d.get("created_utc", time.time())).astimezone(),
                                  payload={"platform": "reddit", "subreddit": d.get("subreddit"), "comments": d.get("num_comments"),
                                           "selftext": (d.get("selftext") or "")[:400]}))
        return out

    async def fetch(self, client, regions, secrets, config):
        self.need(secrets)
        tok = await self._token(client, secrets)
        h = {"Authorization": f"bearer {tok}"}
        out = []
        for reg in regions:
            for sub in reg.get("subreddits", [])[:2]:
                r = await client.get(f"https://oauth.reddit.com/r/{sub}/hot", params={"limit": 8}, headers=h)
                if r.status_code == 200:
                    out += self._items(r.json()["data"]["children"], reg["code"], "social_trend")
        return out

    async def search(self, client, query, regions, secrets, config, limit=10):
        if not (secrets.get("reddit_client_id") and secrets.get("reddit_client_secret")):
            return []
        tok = await self._token(client, secrets)
        r = await client.get("https://oauth.reddit.com/search", params={"q": query, "sort": "new", "limit": limit},
                             headers={"Authorization": f"bearer {tok}"})
        r.raise_for_status()
        return self._items(r.json()["data"]["children"], "*", "social_post")


class YouTubeConnector(BaseConnector):
    spec = ConnectorSpec("youtube", "YouTube trending", "social", "Most popular videos per country; topic search.",
                         secrets=["youtube_api_key"], interval_minutes=180, supports_search=True,
                         license_note="YouTube Data API quota: 10,000 units/day by default (search costs 100).",
                         docs_url="https://developers.google.com/youtube/v3")

    async def fetch(self, client, regions, secrets, config):
        self.need(secrets)

        async def one(reg):
            r = await client.get("https://www.googleapis.com/youtube/v3/videos", params={
                "part": "snippet,statistics", "chart": "mostPopular", "regionCode": reg["yt_region"], "maxResults": 10,
                "key": secrets["youtube_api_key"]})
            r.raise_for_status()
            return [SignalItem("social_trend", reg["code"], v["snippet"]["title"], value=float(v.get("statistics", {}).get("viewCount", 0)),
                               url=f"https://youtu.be/{v['id']}",
                               payload={"platform": "youtube", "channel": v["snippet"].get("channelTitle"),
                                        "category": v["snippet"].get("categoryId")}) for v in r.json().get("items", [])]
        res = await asyncio.gather(*[one(r) for r in regions], return_exceptions=True)
        return [x for lst in res if isinstance(lst, list) for x in lst]

    async def search(self, client, query, regions, secrets, config, limit=10):
        if not secrets.get("youtube_api_key"):
            return []
        reg = regions[0] if regions else {"yt_region": "US", "code": "*"}
        r = await client.get("https://www.googleapis.com/youtube/v3/search", params={
            "part": "snippet", "q": query, "type": "video", "order": "date", "maxResults": limit,
            "regionCode": reg.get("yt_region", "US"), "key": secrets["youtube_api_key"]})
        r.raise_for_status()
        return [SignalItem("social_post", reg.get("code", "*"), f"{i['snippet']['title']} — {i['snippet'].get('description', '')[:200]}",
                           url=f"https://youtu.be/{i['id'].get('videoId')}", observed_at=_iso(i["snippet"].get("publishedAt")),
                           payload={"platform": "youtube", "author": i["snippet"].get("channelTitle", "")}) for i in r.json().get("items", [])]


class XConnector(BaseConnector):
    spec = ConnectorSpec("x", "X (Twitter)", "social", "Recent posts about the content's topic (search API).",
                         secrets=["x_bearer_token"], interval_minutes=0, supports_search=True,
                         license_note="Requires a paid X API tier.", docs_url="https://docs.x.com/x-api/posts/search")

    async def fetch(self, client, regions, secrets, config):
        return []   # X has no affordable trends endpoint; used for listening only

    async def search(self, client, query, regions, secrets, config, limit=10):
        if not secrets.get("x_bearer_token"):
            return []
        r = await client.get("https://api.x.com/2/tweets/search/recent", params={
            "query": f"{query} -is:retweet", "max_results": max(10, min(limit, 100)), "tweet.fields": "created_at,public_metrics,lang",
            "expansions": "author_id", "user.fields": "username"}, headers={"Authorization": f"Bearer {secrets['x_bearer_token']}"})
        r.raise_for_status()
        d = r.json()
        users = {u["id"]: u.get("username", "") for u in (d.get("includes") or {}).get("users", [])}
        out = []
        for t in d.get("data", []) or []:
            m = t.get("public_metrics") or {}
            out.append(SignalItem("social_post", "*", t.get("text", "")[:500], lang=t.get("lang"), observed_at=_iso(t.get("created_at")),
                                  value=float(m.get("like_count", 0) + m.get("retweet_count", 0)),
                                  url=f"https://x.com/i/web/status/{t['id']}",
                                  payload={"platform": "x", "author": users.get(t.get("author_id"), "")}))
        return out
