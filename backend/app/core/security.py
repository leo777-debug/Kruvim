"""Passwords (Argon2id), JWT access tokens, opaque refresh tokens and API keys."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .config import settings

_ph = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
JWT_ALG = "HS256"
API_KEY_PREFIX = "krv_"


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _signing_key() -> str:
    return hmac.new(settings.secret_key.encode(), b"kruvim-jwt-v1", hashlib.sha256).hexdigest()


def create_access_token(user_id: str, org_id: str | None, extra: dict | None = None) -> str:
    now = int(time.time())
    payload = {"sub": user_id, "org": org_id, "iat": now, "exp": now + settings.access_token_minutes * 60, "typ": "access"}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, _signing_key(), algorithm=JWT_ALG)


def decode_access_token(token: str) -> dict:
    data = jwt.decode(token, _signing_key(), algorithms=[JWT_ALG])
    if data.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return data


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    return raw, sha256(raw)


@dataclass
class NewApiKey:
    raw: str
    prefix: str
    hashed: str


def new_api_key() -> NewApiKey:
    body = secrets.token_urlsafe(32)
    raw = API_KEY_PREFIX + body
    return NewApiKey(raw=raw, prefix=raw[:12], hashed=sha256(raw))


def new_invite_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, sha256(raw)
