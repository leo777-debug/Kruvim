"""Claude via the official Anthropic SDK (prompt caching on the shared system prompt, effort
control, server-side refusal fallback on models that support it)."""
from __future__ import annotations

import time

from .base import BaseLLM, LLMAuthError, LLMError, ProviderSettings, Usage

_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
_LIGHT_ROLES = {"voice", "action", "debate", "chat", "brief", "survey", "persona"}


class AnthropicLLM(BaseLLM):
    name = "anthropic"

    def __init__(self, s: ProviderSettings):
        super().__init__(s)
        try:
            import anthropic
        except ImportError:
            raise LLMAuthError("The 'anthropic' package is not installed.")
        self._a = anthropic
        kw = {"max_retries": 3, "timeout": float(s.timeout or 120)}
        if s.api_key:
            kw["api_key"] = s.api_key
        if s.base_url:
            kw["base_url"] = s.base_url
        try:
            self.client = anthropic.AsyncAnthropic(**kw)
        except Exception as exc:
            raise LLMAuthError(f"Anthropic client could not start: {exc}")
        self.custom_base = bool(s.base_url)

    async def complete(self, *, system, user, role, max_tokens, usage: Usage, json_out=True, images=None, temperature=None):
        a = self._a
        model = self.model_for("vision" if images else role)
        if not model:
            raise LLMAuthError(f"No model configured for '{role}'.")
        content: list | str = user
        if images:
            content = [{"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}} for mt, b64 in images]
            content.append({"type": "text", "text": user})
        params = {
            "model": model,
            "max_tokens": max(max_tokens * 3, 4000),   # room for adaptive thinking + the reply
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": content}],
        }
        if "haiku" not in model:
            params["output_config"] = {"effort": "low" if role in _LIGHT_ROLES else "high"}
        async with self.sem:
            t0 = time.time()
            try:
                if model in _FALLBACK_MODELS and not self.custom_base:
                    resp = await self.client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
                else:
                    resp = await self.client.messages.create(**params)
            except a.AuthenticationError as exc:
                usage.fail(self.name, role)
                raise LLMAuthError(f"Anthropic rejected the API key: {exc.message}")
            except a.NotFoundError as exc:
                usage.fail(self.name, role)
                raise LLMAuthError(f"Model '{model}' not found: {exc.message}")
            except a.PermissionDeniedError as exc:
                usage.fail(self.name, role)
                raise LLMAuthError(f"Permission denied: {exc.message}")
            except a.BadRequestError as exc:
                if "output_config" in params and "effort" in str(exc.message).lower():
                    params.pop("output_config")
                    resp = await self.client.messages.create(**params)
                else:
                    usage.fail(self.name, role)
                    raise LLMError(f"Bad request: {exc.message}")
            except a.RateLimitError as exc:
                usage.fail(self.name, role)
                raise LLMError(f"Rate limited after retries: {exc.message}")
            except a.APIStatusError as exc:
                usage.fail(self.name, role)
                raise LLMError(f"Anthropic API error {exc.status_code}: {exc.message}")
            except a.APIConnectionError as exc:
                usage.fail(self.name, role)
                raise LLMAuthError(f"Cannot reach the Anthropic API: {exc}")
        if resp.stop_reason == "refusal":
            usage.fail(self.name, role)
            raise LLMError("model declined this request")
        u = resp.usage
        cached = int(u.cache_read_input_tokens or 0)
        total_in = int((u.input_tokens or 0) + cached + (u.cache_creation_input_tokens or 0))
        usage.add(self.name, model, role, total_in, cached, int(u.output_tokens or 0), time.time() - t0)
        return "".join(b.text for b in resp.content if b.type == "text")

    async def list_models(self) -> list[str]:
        return [m.id async for m in self.client.models.list()]

    async def aclose(self):
        await self.client.close()
