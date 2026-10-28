"""Encryption at rest for third-party secrets (LLM keys, connector credentials).

Rotating KRUVIM_SECRET_KEY: move the old value to KRUVIM_PREVIOUS_SECRET_KEYS (comma separated), deploy, then run
`python -m scripts.rotate_secrets` to re-encrypt everything with the new key. Until then, old values still decrypt."""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from .config import settings

log = logging.getLogger("kruvim.crypto")


def _key(secret: str) -> Fernet:
    raw = hmac.new(secret.encode(), b"kruvim-secrets-v1", hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def _fernet() -> MultiFernet:
    return MultiFernet([_key(settings.secret_key), *(_key(k) for k in settings.previous_secret_keys)])


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
        # Treated as "no key" so runs fall back cleanly, but never silently: this means the secret key changed.
        log.warning("a stored secret could not be decrypted; add the old KRUVIM_SECRET_KEY to KRUVIM_PREVIOUS_SECRET_KEYS")
        return ""


def rotate(token: str | None) -> str | None:
    """Re-encrypt a stored value with the current key (raises InvalidToken if no configured key can read it)."""
    if not token:
        return token
    return _fernet().rotate(token.encode()).decode()


def mask(value: str | None) -> str:
    if not value:
        return ""
    return value[:3] + "…" + value[-4:] if len(value) > 10 else "set"
