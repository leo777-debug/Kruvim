"""Model-provider key vault: one encrypted key per provider per workspace, validated before it is stored.

Adding a provider = one entry in KEY_PROVIDERS (and a matching preset in app.services.llm.PRESETS).
Keys are encrypted with app.core.crypto, only ever leave the server in masked form, and are never logged."""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.crypto import mask
from app.core.netguard import check_url_shape, model_client, private_model_urls_allowed, public_client


@dataclass(frozen=True)
class KeyProvider:
    label: str
    check_url: str = ""            # hosted providers: fixed address; others use the saved base URL + /models
    auth: str = "bearer"           # bearer | x-api-key
    needs_base_url: bool = False
    key_hint: str = ""             # what a key usually starts with, shown as a placeholder
    docs: str = ""


KEY_PROVIDERS: dict[str, KeyProvider] = {
    "openai": KeyProvider("OpenAI", "https://api.openai.com/v1/models", key_hint="sk-", docs="https://platform.openai.com/api-keys"),
    "anthropic": KeyProvider("Anthropic (Claude)", "https://api.anthropic.com/v1/models", auth="x-api-key", key_hint="sk-ant-",
                             docs="https://console.anthropic.com/settings/keys"),
    "openrouter": KeyProvider("OpenRouter", "https://openrouter.ai/api/v1/key", key_hint="sk-or-", docs="https://openrouter.ai/keys"),
    "gemini": KeyProvider("Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai/models", key_hint="AIza",
                          docs="https://aistudio.google.com/apikey"),
    "deepseek": KeyProvider("DeepSeek", "https://api.deepseek.com/models", key_hint="sk-", docs="https://platform.deepseek.com/api_keys"),
    "groq": KeyProvider("Groq", "https://api.groq.com/openai/v1/models", key_hint="gsk_", docs="https://console.groq.com/keys"),
    "together": KeyProvider("Together AI", "https://api.together.xyz/v1/models", docs="https://api.together.ai/settings/api-keys"),
    "custom": KeyProvider("Other OpenAI-compatible", needs_base_url=True),
}
# Local servers (Ollama, LM Studio, llama.cpp, vLLM) need no key: they are chosen and tested under Model provider.

ANTHROPIC_VERSION = "2023-06-01"


class KeyRejected(Exception):
    """The provider answered and refused the key (or the address is not allowed)."""


@dataclass
class Check:
    ok: bool
    message: str


def public_catalog() -> list[dict]:
    return [{"id": k, "label": p.label, "needs_base_url": p.needs_base_url, "key_hint": p.key_hint, "docs": p.docs}
            for k, p in KEY_PROVIDERS.items()]


def hint(key: str) -> str:
    return mask(key) if key else ""


async def validate(provider: str, key: str, base_url: str = "", *, timeout: float = 15) -> Check:
    """A lightweight authenticated read (model or key listing): costs no tokens. Raises KeyRejected on a definite no."""
    spec = KEY_PROVIDERS[provider]
    if not key:
        raise KeyRejected("Enter the API key.")
    if spec.needs_base_url:
        if not base_url:
            raise KeyRejected("Enter the server's base URL (it usually ends in /v1).")
        try:
            check_url_shape(base_url, require_https=not private_model_urls_allowed())
        except ValueError as exc:
            raise KeyRejected(f"Base URL: {exc}")
        url, client = base_url.rstrip("/") + "/models", model_client(timeout=timeout)
    else:
        url, client = spec.check_url, public_client(timeout=timeout)
    headers = {}
    if spec.auth == "bearer":
        headers["Authorization"] = f"Bearer {key}"
    elif spec.auth == "x-api-key":
        headers.update({"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION})
    try:
        async with client:
            r = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        # Never echo the exception text: some clients include request headers in it.
        return Check(False, f"Could not reach {spec.label} ({exc.__class__.__name__}). Check the address and try again.")
    if r.status_code in (401, 403):
        raise KeyRejected(f"{spec.label} rejected this key. Check that it was copied in full and is still active.")
    if r.status_code == 429:
        return Check(True, f"{spec.label} accepted the key but is rate limiting it right now (or its credit is used up).")
    if r.status_code >= 400:
        return Check(False, f"{spec.label} answered with an unexpected status ({r.status_code}). Try again in a minute.")
    return Check(True, f"{spec.label} accepted the key.")
