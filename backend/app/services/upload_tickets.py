"""Purpose-bound upload receipts; no storage credentials or client-chosen keys."""
import hashlib
import hmac
import time

import jwt

from app.core.config import settings
from app.core.errors import AppError


def _key():
    return hmac.new(settings.secret_key.encode(), b"kruvim-upload-v1", hashlib.sha256).digest()


def issue(claims):
    return jwt.encode({**claims, "exp": int(time.time()) + 7200, "aud": "asset-upload"}, _key(), algorithm="HS256")


def verify(token, org_id, user_id, project_id):
    try:
        data = jwt.decode(token, _key(), algorithms=["HS256"], audience="asset-upload",
                          options={"require": ["exp", "aud", "org", "sub", "project", "id", "key", "size", "mime", "filename", "kind"]})
        if (data["org"], data["sub"], data["project"]) != (org_id, user_id, project_id):
            raise ValueError("wrong owner")
        return data
    except (jwt.InvalidTokenError, ValueError):
        raise AppError("Upload authorization is invalid or expired. Please upload again.", status=403)
