"""Domain errors mapped to consistent JSON responses: {"error": {"code", "message"}}."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status:
            self.status = status
        self.details = details


class NotFound(AppError):
    status, code = 404, "not_found"


class Forbidden(AppError):
    status, code = 403, "forbidden"


class Unauthorized(AppError):
    status, code = 401, "unauthorized"


class Conflict(AppError):
    status, code = 409, "conflict"


class QuotaExceeded(AppError):
    status, code = 402, "quota_exceeded"


class RateLimited(AppError):
    status, code = 429, "rate_limited"


def _body(code: str, message: str, details=None):
    b = {"error": {"code": code, "message": message}}
    if details:
        b["error"]["details"] = details
    return b


def install(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        headers = {"Retry-After": "60"} if isinstance(exc, RateLimited) else None
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status, headers=headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return JSONResponse(_body("http_" + str(exc.status_code), str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        errs = [{"loc": ".".join(str(x) for x in e["loc"][1:]), "msg": e["msg"]} for e in exc.errors()]
        first = errs[0] if errs else {"loc": "", "msg": "invalid"}
        return JSONResponse(_body("validation_error", f"{first['loc']}: {first['msg']}", errs), status_code=422)
