"""Any OpenAI-compatible /chat/completions endpoint: DeepSeek, OpenRouter, OpenAI, Groq, Together,
Ollama, LM Studio, llama.cpp server, vLLM. Capabilities (JSON mode, temperature, max_tokens name)
are discovered from 400 responses and remembered for the client's lifetime."""
from __future__ import annotations

import asyncio
import random
import time

import httpx

from .base import BaseLLM, LLMAuthError, LLMError, ProviderSettings, Usage
from .errors import ProviderFailure, classify, retry_delay


class OpenAICompatLLM(BaseLLM):
    name = "openai"

    def __init__(self, s: ProviderSettings):
        super().__init__(s)
        base = (s.base_url or "").rstrip("/")
        if not base:
            raise LLMAuthError("No base URL configured for this provider.")
        self.base = base
        headers = {"Content-Type": "application/json"}
        if s.api_key:
            headers["Authorization"] = f"Bearer {s.api_key}"
        if "openrouter.ai" in base:
            headers["HTTP-Referer"] = "https://kruvim.app"
            headers["X-Title"] = "Kruvim"
        self.client = httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(float(s.timeout or 120), connect=10),
                                        limits=httpx.Limits(max_connections=max(8, s.concurrency * 2)))
        self.json_ok = bool(s.json_mode)
        self.temp_ok = True
        self.max_tokens_key = "max_completion_tokens" if base == "https://api.openai.com/v1" else "max_tokens"

    async def complete(self, *, system, user, role, max_tokens, usage: Usage, json_out=True, images=None, temperature=None):
        model = self.model_for("vision" if images else role)
        if not model:
            raise LLMAuthError(f"No model configured for '{role}'. Set one in Settings → Model providers.")
        content = user
        if images:
            content = [{"type": "text", "text": user}] + [
                {"type": "image_url", "image_url": {"url": f"data:{mt};base64,{b64}"}} for mt, b64 in images]
        async with self.sem:
            from app.services.llm.errors import BudgetPause
            from app.services.token_budget import current
            if current.get() and current.get().paused:
                raise BudgetPause(current.get().paused)
            from app.core.config import settings
            attempts = 1 if settings.billing_enabled and self.s.billing_metered else 4
            for attempt in range(attempts):
                body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
                        self.max_tokens_key: max_tokens, "stream": False}
                if self.temp_ok:
                    body["temperature"] = self.s.temperature if temperature is None else temperature
                if json_out and self.json_ok:
                    body["response_format"] = {"type": "json_object"}
                t0 = time.time()
                try:
                    r = await self.client.post(self.base + "/chat/completions", json=body)
                except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                    if attempt < attempts - 1:
                        await asyncio.sleep(min(8, 1.5 * 2 ** attempt))
                        continue
                    usage.fail(self.name, role)
                    raise ProviderFailure(classify(None, settings=self.s, network_error=True), exc.__class__.__name__)
                except (httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.WriteTimeout) as exc:
                    if attempt == attempts - 1:
                        usage.fail(self.name, role)
                        raise ProviderFailure(classify(None, settings=self.s, network_error=True), exc.__class__.__name__)
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                if self.base == "https://api.openai.com/v1" and r.status_code in (400, 401, 403, 404, 429):
                    usage.rejected = True
                if r.status_code == 400:
                    try:
                        issue = classify(r.status_code, r.json(), settings=self.s)
                    except ValueError:
                        issue = classify(r.status_code, settings=self.s)
                    if issue.category == 'quota_exhausted':
                        usage.fail(self.name, role)
                        raise ProviderFailure(issue, r.text[:2000])
                    msg = r.text.lower()
                    changed = False
                    if "response_format" in msg or "json_object" in msg or "json mode" in msg:
                        self.json_ok, changed = False, True
                    if "temperature" in msg and self.temp_ok:
                        self.temp_ok, changed = False, True
                    if "max_completion_tokens" in msg and self.max_tokens_key == "max_tokens":
                        self.max_tokens_key, changed = "max_completion_tokens", True
                    if changed:
                        continue
                    usage.fail(self.name, role)
                    raise LLMError('The model provider rejected this request. Check the model settings.')
                if r.status_code in (401, 403):
                    usage.fail(self.name, role)
                    raise ProviderFailure(classify(r.status_code, settings=self.s), r.text[:2000])
                if r.status_code == 404:
                    usage.fail(self.name, role)
                    raise LLMAuthError("The configured model or endpoint could not be found. Check Settings.")
                if r.status_code == 402:
                    usage.fail(self.name, role)
                    raise ProviderFailure(classify(402, settings=self.s), r.text[:2000])
                if r.status_code == 429 or r.status_code >= 500:
                    try:
                        issue = classify(r.status_code, r.json(), settings=self.s)
                    except ValueError:
                        issue = classify(r.status_code, settings=self.s)
                    if not issue.retryable:
                        usage.fail(self.name, role)
                        raise ProviderFailure(issue, r.text[:2000])
                    if attempt == attempts - 1:
                        usage.fail(self.name, role)
                        raise ProviderFailure(issue, r.text[:2000])
                    delay = retry_delay(r.headers, 1.5 * 2 ** attempt + random.random())
                    if delay > self.s.timeout * 4:
                        raise ProviderFailure(issue, 'Provider retry delay exceeds this request deadline')
                    await asyncio.sleep(delay)
                    continue
                if r.status_code != 200:
                    usage.fail(self.name, role)
                    raise ProviderFailure(classify(r.status_code, settings=self.s), r.text[:2000])
                try:
                    data = r.json()
                    if not isinstance(data, dict):
                        raise ValueError("expected an object")
                except ValueError as exc:
                    if attempt < attempts - 1:
                        await asyncio.sleep(min(8, 1.5 * 2 ** attempt))
                        continue
                    usage.fail(self.name, role)
                    raise LLMError("The model server returned an unreadable response.") from exc
                u = data.get("usage") or {}
                cached = u.get("prompt_cache_hit_tokens") or (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
                usage.add(self.name, model, role, int(u.get("prompt_tokens") or 0), int(cached or 0),
                          int(u.get("completion_tokens") or 0), time.time() - t0)
                try:
                    msg = data["choices"][0]["message"]
                except (KeyError, IndexError):
                    raise LLMError("The model provider returned an unexpected response.")
                return msg.get("content") or msg.get("reasoning_content") or ""
        raise LLMError("unreachable")

    async def list_models(self) -> list[str]:
        r = await self.client.get(self.base + "/models")
        if r.status_code in (401, 403):
            raise LLMAuthError("API key rejected while listing models")
        r.raise_for_status()
        data = r.json()
        items = data.get("data") if isinstance(data, dict) else data
        return sorted({(m.get("id") or m.get("name")) for m in (items or []) if isinstance(m, dict)} - {None})

    async def aclose(self):
        await self.client.aclose()
