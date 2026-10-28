"""Reading and parsing uploaded files without letting one file stall or exhaust the API."""
from __future__ import annotations

import asyncio

from fastapi import UploadFile

from .errors import AppError

PARSE_TIMEOUT_SECONDS = 90


async def read_limited(file: UploadFile, limit_bytes: int) -> bytes:
    """Read an upload in chunks and stop as soon as it passes the limit."""
    data = bytearray()
    while chunk := await file.read(1 << 20):
        data.extend(chunk)
        if len(data) > limit_bytes:
            raise AppError(f"File larger than {limit_bytes // (1024 * 1024)} MB.", code="too_large", status=413)
    return bytes(data)


async def parse_off_loop(fn, *args, timeout: float = PARSE_TIMEOUT_SECONDS):
    """Parse in a worker thread: a large or crafted PDF, workbook or CSV cannot block other requests."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout)
    except TimeoutError:
        raise AppError("This file took too long to read. Split it into smaller files and try again.", code="parse_timeout",
                       status=422)
