"""Official read-only analytics APIs. Never fetch comments or follower identities.

Unsupported/privacy-suppressed measurements stay null; they are never estimated.
"""
from __future__ import annotations

import json
from datetime import timedelta
from urllib.parse import urlencode

from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.db.base import utcnow

PROVIDERS = {
    "youtube": {"authorize": "https://accounts.google.com/o/oauth2/v2/auth", "token": "https://oauth2.googleapis.com/token",
                "scope": "https://www.googleapis.com/auth/yt-analytics.readonly https://www.googleapis.com/auth/youtube.readonly",
                "audience_kind": "viewer", "limitations": "Demographics describe viewers, not followers. Privacy thresholds apply."},
    "tiktok": {"authorize": "https://www.tiktok.com/v2/auth/authorize/", "token": "https://open.tiktokapis.com/v2/oauth/token/",
               "scope": "user.info.basic,user.info.stats,video.list", "audience_kind": None,
               "limitations": "The Display API exposes views and engagement counts, but no retention or follower demographics."},
    "instagram": {"authorize": "https://www.instagram.com/oauth/authorize", "token": "https://api.instagram.com/oauth/access_token",
                  "scope": "instagram_business_basic,instagram_business_manage_insights", "audience_kind": "follower",
                  "limitations": "Requires a professional account and approved insights permissions. Retention is unavailable through this connector."},
}


def credentials(platform):
    return getattr(settings, f"{platform}_client_id"), getattr(settings, f"{platform}_client_secret")


def redirect_uri(platform):
    return f"{settings.public_url.rstrip('/')}/api/v1/social/{platform}/callback"


def authorize_url(platform, state):
    client_id, _ = credentials(platform)
    params = {"client_id": client_id, "redirect_uri": redirect_uri(platform), "response_type": "code",
              "scope": PROVIDERS[platform]["scope"], "state": state}
    if platform == "tiktok":
        params["client_key"] = params.pop("client_id")
    if platform == "youtube":
        params.update(access_type="offline", prompt="consent")
    if platform == "instagram":
        params.update(enable_fb_login="0", force_authentication="1")
    return PROVIDERS[platform]["authorize"] + "?" + urlencode(params)


async def request(client, method, url, **kwargs):
    response = await client.request(method, url, **kwargs)
    # Do not include response bodies or URLs in errors: providers can echo credentials.
    if response.status_code >= 400:
        raise ValueError(f"Analytics provider returned HTTP {response.status_code}. Check permissions or reconnect.")
    data = response.json()
    error = data.get("error")
    if error and (not isinstance(error, dict) or error.get("code") not in (None, "ok", 0)):
        raise ValueError("Analytics provider rejected the request. Check permissions or reconnect.")
    return data


async def exchange(client, platform, code):
    cid, secret = credentials(platform)
    body = {"client_id": cid, "client_secret": secret, "code": code, "grant_type": "authorization_code",
            "redirect_uri": redirect_uri(platform)}
    if platform == "tiktok":
        body["client_key"] = body.pop("client_id")
    token = await request(client, "POST", PROVIDERS[platform]["token"], data=body)
    if platform == "instagram":
        token = await request(client, "GET", "https://graph.instagram.com/access_token", params={
            "grant_type": "ig_exchange_token", "client_secret": secret, "access_token": token["access_token"]})
    if not token.get("access_token"):
        raise ValueError("Provider did not return an access token.")
    return token


def save_tokens(row, token):
    old = json.loads(decrypt(row.tokens_enc) or "{}")
    row.tokens_enc = encrypt(json.dumps({**old, **token}))
    row.expires_at = utcnow() + timedelta(seconds=int(token.get("expires_in", 3600)))


async def access_token(client, row):
    token = json.loads(decrypt(row.tokens_enc) or "{}")
    if row.expires_at and row.expires_at <= utcnow() + timedelta(minutes=5):
        cid, secret = credentials(row.platform)
        if row.platform == "instagram":
            new = await request(client, "GET", "https://graph.instagram.com/refresh_access_token", params={
                "grant_type": "ig_refresh_token", "access_token": token["access_token"]})
        else:
            if not token.get("refresh_token"):
                raise ValueError("Analytics authorization expired. Reconnect this account.")
            body = {"client_secret": secret, "grant_type": "refresh_token", "refresh_token": token["refresh_token"],
                    "client_key" if row.platform == "tiktok" else "client_id": cid}
            new = await request(client, "POST", PROVIDERS[row.platform]["token"], data=body)
        save_tokens(row, new)
        token.update(new)
    return token["access_token"]


async def identity(client, platform, token):
    headers = {"Authorization": f"Bearer {token}"}
    if platform == "youtube":
        d = await request(client, "GET", "https://www.googleapis.com/youtube/v3/channels", headers=headers,
                          params={"part": "snippet,statistics", "mine": "true"})
        if not d.get("items"):
            raise ValueError("No YouTube channel is available on this account.")
        u = d["items"][0]
        return u["id"], u["snippet"]["title"]
    if platform == "tiktok":
        d = await request(client, "GET", "https://open.tiktokapis.com/v2/user/info/", headers=headers,
                          params={"fields": "open_id,display_name"})
        u = d["data"]["user"]
        return u["open_id"], u["display_name"]
    d = await request(client, "GET", "https://graph.instagram.com/me", headers=headers, params={"fields": "user_id,username"})
    return str(d["user_id"]), d["username"]


def normalize_split(split):
    total = sum(float(v) for v in split.values())
    return {k: round(100 * float(v) / total, 4) for k, v in split.items()} if total > 0 else {}


async def audience(client, row, token):
    headers = {"Authorization": f"Bearer {token}"}
    result = {"kind": PROVIDERS[row.platform]["audience_kind"], "countries": {}, "ages": {}, "genders": {},
              "fetched_at": utcnow().isoformat(), "limitations": PROVIDERS[row.platform]["limitations"]}
    if row.platform == "tiktok":
        return result
    if row.platform == "youtube":
        params = {"ids": "channel==MINE", "startDate": (utcnow() - timedelta(days=90)).date().isoformat(),
                  "endDate": (utcnow() - timedelta(days=2)).date().isoformat(), "filters": "isSubscribed==subscribed"}
        # Country reports use views; age/gender reports use viewerPercentage.
        for dimension, metric in (("country", "views"), ("ageGroup,gender", "viewerPercentage")):
            try:
                d = await request(client, "GET", "https://youtubeanalytics.googleapis.com/v2/reports", headers=headers,
                                  params={**params, "dimensions": dimension, "metrics": metric})
                for values in d.get("rows", []):
                    if dimension == "country":
                        result["countries"][values[0]] = values[1]
                    else:
                        age = values[0].removeprefix("age").replace("65-", "65+")
                        result["ages"][age] = result["ages"].get(age, 0) + values[2]
                        result["genders"][values[1]] = result["genders"].get(values[1], 0) + values[2]
            except ValueError:
                result["limitations"] += f" {dimension} unavailable or privacy-suppressed."
        result["kind"] = "subscribed_viewer"
    else:
        for dimension, key in (("country", "countries"), ("age", "ages"), ("gender", "genders")):
            try:
                d = await request(client, "GET", f"https://graph.instagram.com/{settings.instagram_api_version}/{row.account_id}/insights",
                                  headers=headers, params={"metric": "follower_demographics", "period": "lifetime",
                                                          "metric_type": "total_value", "breakdown": dimension, "timeframe": "last_90_days"})
                for item in d.get("data", []):
                    for breakdown in item.get("total_value", {}).get("breakdowns", []):
                        for value in breakdown.get("results", []):
                            label = value["dimension_values"][0]
                            if dimension == "gender":
                                label = {"M": "male", "F": "female", "U": "unknown"}.get(label, label)
                            result[key][label] = value["value"]
            except ValueError:
                result["limitations"] += f" {dimension} unavailable or privacy-suppressed."
    for key in ("countries", "ages", "genders"):
        result[key] = normalize_split(result[key])
    return result


async def outcome(client, row, post_id, token):
    headers = {"Authorization": f"Bearer {token}"}
    published = None
    metrics = {"views": None, "likes": None, "shares": None, "comments": None, "retention": None}
    if row.platform == "tiktok":
        d = await request(client, "POST", "https://open.tiktokapis.com/v2/video/query/", headers=headers,
                          params={"fields": "id,create_time,view_count,like_count,share_count,comment_count"},
                          json={"filters": {"video_ids": [post_id]}})
        videos = d.get("data", {}).get("videos", [])
        if not videos:
            raise ValueError("Post not found in the connected TikTok account.")
        video = videos[0]
        from datetime import UTC, datetime
        published = datetime.fromtimestamp(video["create_time"], UTC)
        metrics.update({k: video.get(v) for k, v in (("views", "view_count"), ("likes", "like_count"),
                                                   ("shares", "share_count"), ("comments", "comment_count"))})
    elif row.platform == "youtube":
        d = await request(client, "GET", "https://www.googleapis.com/youtube/v3/videos", headers=headers,
                          params={"part": "snippet", "id": post_id})
        if not d.get("items") or d["items"][0]["snippet"]["channelId"] != row.account_id:
            raise ValueError("Video does not belong to the connected YouTube channel.")
        from datetime import datetime
        published = datetime.fromisoformat(d["items"][0]["snippet"]["publishedAt"].replace("Z", "+00:00"))
        d = await request(client, "GET", "https://youtubeanalytics.googleapis.com/v2/reports", headers=headers, params={
            "ids": "channel==MINE", "startDate": published.date().isoformat(), "endDate": utcnow().date().isoformat(),
            "filters": f"video=={post_id}", "metrics": "views,likes,shares,comments,averageViewPercentage"})
        if not d.get("rows"):
            raise ValueError("YouTube analytics are not available for this video yet.")
        metrics.update(dict(zip(metrics, d["rows"][0])))
        metrics["retention"] = min(100, metrics["retention"])  # replays can exceed 100% on YouTube
    else:
        base = f"https://graph.instagram.com/{settings.instagram_api_version}"
        d = await request(client, "GET", f"{base}/{post_id}", headers=headers, params={"fields": "id,owner,timestamp"})
        owner = d.get("owner", {})
        if str(owner.get("id") if isinstance(owner, dict) else owner) != row.account_id:
            raise ValueError("Post does not belong to the connected Instagram account.")
        from datetime import datetime
        published = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00"))
        # Fetch metrics separately: one unsupported metric must not erase the available ones.
        for metric, key in (("views", "views"), ("likes", "likes"), ("shares", "shares"), ("comments", "comments")):
            try:
                d = await request(client, "GET", f"{base}/{post_id}/insights", headers=headers, params={"metric": metric})
                item = d.get("data", [{}])[0]
                metrics[key] = item.get("total_value", {}).get("value", (item.get("values") or [{}])[0].get("value"))
            except ValueError:
                pass
        if metrics["views"] is None:
            raise ValueError("Instagram views are unavailable for this post. Check insights permissions and media eligibility.")
    if metrics["views"] and all(metrics[k] is not None for k in ("likes", "shares", "comments")):
        metrics["engagement_rate"] = round(100 * sum(metrics[k] for k in ("likes", "shares", "comments")) / metrics["views"], 3)
    else:
        metrics["engagement_rate"] = None
    return metrics, published
