"""Request id, access logging, metrics and security headers (pure ASGI, streaming-safe)."""
from __future__ import annotations

import json
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
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),   # API responses are data, never pages
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
                status_holder["started"] = True
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", rid.encode()))
                existing = {k.lower() for k, _ in headers}
                headers.extend((k, v) for k, v in SECURITY_HEADERS if k not in existing)
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception:
            # Never a stack trace or plain-text error page: log it with the request id and give the user that id.
            log.exception("unhandled error", extra={"method": scope["method"], "path": scope["path"]})
            if "started" in status_holder:
                raise
            await _send_error(_send, rid)
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


async def _send_error(send, rid: str) -> None:
    body = json.dumps({"error": {"code": "internal_error", "request_id": rid,
                                 "message": f"Something went wrong on our side. Please try again; if it keeps happening, "
                                            f"contact support and quote reference {rid}."}}).encode()
    await send({"type": "http.response.start", "status": 500,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
