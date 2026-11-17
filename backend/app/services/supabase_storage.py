"""Private Supabase Storage access. Credentials never leave the backend."""
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.core.errors import AppError


async def request(method, path, **kwargs):
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise AppError("Supabase Storage is not configured.", status=503)
    headers = kwargs.pop("headers", {})
    headers.update({"apikey": settings.supabase_secret_key, "Authorization": "Bearer " + settings.supabase_secret_key})
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.request(method, settings.supabase_url.rstrip("/") + "/storage/v1/" + path,
            headers=headers, **kwargs)
    if response.status_code >= 400:
        # Do not include response bodies, URLs or credentials in public errors.
        raise AppError(f"Supabase Storage request failed ({response.status_code}).", status=502)
    return response


def object_path(key):
    if not key or key.startswith("/") or ".." in key.split("/"):
        raise ValueError("Invalid object key")
    return quote(settings.supabase_bucket, safe="") + "/" + quote(key, safe="/")


async def put(key, raw):
    await request("POST", "object/" + object_path(key), content=raw,
        headers={"x-upsert": "true", "Content-Type": "application/octet-stream"})


async def get(key):
    return (await request("GET", "object/" + object_path(key))).content


async def signed_upload(key, mime, size):
    bucket = (await request("GET", "bucket/" + quote(settings.supabase_bucket, safe=""))).json()
    limit = bucket.get("file_size_limit")
    if limit and size > int(limit):
        raise AppError(f"Storage currently accepts files up to {int(limit) / (1024 * 1024):g} MB. Choose a smaller file.",
                       code="too_large", status=413)
    response = await request("POST", "object/upload/sign/" + object_path(key), json={})
    url = response.json()["url"]
    return {"url": settings.supabase_url.rstrip("/") + "/storage/v1" + url,
            "method": "PUT", "headers": {"Content-Type": mime, "x-upsert": "false"}}


async def info(key):
    data = (await request("GET", "object/info/" + object_path(key))).json()
    metadata = data.get("metadata") or {}
    return {"size": int(metadata.get("size", data.get("size", -1))),
            "mime": metadata.get("mimetype", data.get("contentType", ""))}


async def delete(key):
    await request("DELETE", "object/" + quote(settings.supabase_bucket, safe=""), json={"prefixes": [key]})


async def list_files(prefix):
    response = await request("POST", "object/list/" + quote(settings.supabase_bucket, safe=""),
        json={"prefix": prefix, "limit": 100, "sortBy": {"column": "name", "order": "asc"}})
    return [x for x in response.json() if x.get("id") and x.get("name", "").lower().endswith((".csv", ".xlsx"))]
