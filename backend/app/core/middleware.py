"""Request id, access logging, metrics and security headers (pure ASGI, streaming-safe)."""
from __future__ import annotations

import logging
import re
import time
import uuid

from .logging import request_id_var
from .metrics import HTTP_LATENCY, HTTP_REQUESTS

log = logging.getLogger("kruvim.http")

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        rid = None
        for k, v in scope.get("headers", []):
            if k == b"x-request-id":
                candidate = v.decode(errors="ignore")[:64]
                rid = candidate if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", candidate) else None
        rid = rid or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status_holder = {"status": 500}

        async def _send(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", rid.encode()))
                headers.extend(SECURITY_HEADERS)
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            dur = time.perf_counter() - start
            route = scope.get("route")
            path = getattr(route, "path", None) or ("static" if not scope["path"].startswith("/api") else "unmatched")
            HTTP_REQUESTS.labels(scope["method"], path, str(status_holder["status"])).inc()
            HTTP_LATENCY.labels(scope["method"], path).observe(dur)
            if scope["path"].startswith("/api") and not scope["path"].endswith("/events"):
                log.info("request", extra={"method": scope["method"], "path": scope["path"],
                                           "status": status_holder["status"], "duration_ms": round(dur * 1000, 1)})
            request_id_var.reset(token)
