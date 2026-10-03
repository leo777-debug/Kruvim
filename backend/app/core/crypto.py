"""Encryption at rest for third-party secrets (LLM keys, connector credentials)."""
from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

from .config import settings


def _fernet() -> Fernet:
    raw = hmac.new(settings.secret_key.encode(), b"kruvim-secrets-v1", hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str | None) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return ""


def mask(value: str | None) -> str:
    if not value:
        return ""
    return value[:3] + "…" + value[-4:] if len(value) > 10 else "set"
