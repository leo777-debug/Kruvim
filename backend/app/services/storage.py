"""Object storage: local volume (default) or any S3-compatible bucket (AWS, R2, MinIO)."""
from __future__ import annotations

import asyncio
import os
import tempfile

from app.core.config import settings
from app.core.errors import AppError


async def signed_upload(key: str, mime: str, size: int) -> dict:
    if settings.storage_backend == "supabase":
        from app.services.supabase_storage import signed_upload as cloud_sign
        return await cloud_sign(key, mime, size)
    if settings.storage_backend == "s3":
        url = await asyncio.to_thread(_s3().generate_presigned_url, "put_object",
            Params={"Bucket": settings.s3_bucket, "Key": key, "ContentType": mime, "IfNoneMatch": "*"}, ExpiresIn=7200)
        return {"url": url, "method": "PUT", "headers": {"Content-Type": mime, "If-None-Match": "*"}}
    raise AppError("Direct uploads require cloud storage.", status=503)


async def info(key: str) -> dict:
    if settings.storage_backend == "supabase":
        from app.services.supabase_storage import info as cloud_info
        return await cloud_info(key)
    if settings.storage_backend == "s3":
        data = await asyncio.to_thread(_s3().head_object, Bucket=settings.s3_bucket, Key=key)
        return {"size": data["ContentLength"], "mime": data["ContentType"]}
    return {"size": os.path.getsize(_local_path(key)), "mime": "application/octet-stream"}


def _local_path(key: str) -> str:
    root = os.path.realpath(os.path.join(settings.data_dir, "objects"))
    p = os.path.realpath(os.path.join(root, key))
    if os.path.normcase(os.path.commonpath([root, p])) != os.path.normcase(root) or p == root:
        raise ValueError("invalid storage key")
    return p


def _s3():
    import boto3  # optional dependency
    return boto3.client("s3", endpoint_url=settings.s3_endpoint_url, region_name=settings.s3_region)


async def put(key: str, data: bytes) -> None:
    if settings.storage_backend == "supabase":
        from app.services.supabase_storage import put as cloud_put
        return await cloud_put(key, data)
    if settings.storage_backend == "s3":
        await asyncio.to_thread(_s3().put_object, Bucket=settings.s3_bucket, Key=key, Body=data)
        return
    p = _local_path(key)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    await asyncio.to_thread(_write, p, data)


def _write(p: str, data: bytes):
    with open(p, "wb") as f:
        f.write(data)


async def get(key: str) -> bytes:
    if settings.storage_backend == "supabase":
        from app.services.supabase_storage import get as cloud_get
        return await cloud_get(key)
    if settings.storage_backend == "s3":
        obj = await asyncio.to_thread(_s3().get_object, Bucket=settings.s3_bucket, Key=key)
        return obj["Body"].read()
    with open(_local_path(key), "rb") as f:
        return f.read()


async def local_file(key: str, suffix: str = "") -> str:
    """A filesystem path for tools like ffmpeg (downloads from S3 to a temp file when needed)."""
    if settings.storage_backend == "local":
        return _local_path(key)
    data = await get(key)
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


async def delete(key: str) -> None:
    if settings.storage_backend == "supabase":
        from app.services.supabase_storage import delete as cloud_delete
        return await cloud_delete(key)
    if settings.storage_backend == "s3":
        await asyncio.to_thread(_s3().delete_object, Bucket=settings.s3_bucket, Key=key)
        return
    try:
        os.remove(_local_path(key))
    except FileNotFoundError:
        pass
