"""Any OpenAI-compatible /chat/completions endpoint: DeepSeek, OpenRouter, OpenAI, Groq, Together,
Ollama, LM Studio, llama.cpp server, vLLM. Capabilities (JSON mode, temperature, max_tokens name)
are discovered from 400 responses and remembered for the client's lifetime."""
from __future__ import annotations

import asyncio
import random
import time

import httpx

from .base import BaseLLM, LLMAuthError, LLMError, ProviderSettings, Usage


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
        self.max_tokens_key = "max_tokens"

    async def complete(self, *, system, user, role, max_tokens, usage: Usage, json_out=True, images=None, temperature=None):
        model = self.model_for("vision" if images else role)
        if not model:
            raise LLMAuthError(f"No model configured for '{role}'. Set one in Settings → Model providers.")
        content = user
        if images:
            content = [{"type": "text", "text": user}] + [
                {"type": "image_url", "image_url": {"url": f"data:{mt};base64,{b64}"}} for mt, b64 in images]
        async with self.sem:
            for attempt in range(4):
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
                    usage.fail(self.name, role)
                    raise LLMAuthError(f"Cannot reach {self.base} ({exc.__class__.__name__}). Is the model server running?")
                except (httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.WriteTimeout) as exc:
                    if attempt == 3:
                        usage.fail(self.name, role)
                        raise LLMError(f"timeout talking to {self.base}: {exc.__class__.__name__}")
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                if r.status_code == 400:
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
                    raise LLMError(f"400 from provider: {r.text[:300]}")
                if r.status_code in (401, 403):
                    usage.fail(self.name, role)
                    raise LLMAuthError(f"{r.status_code} from provider: check the API key. {r.text[:200]}")
                if r.status_code == 404:
                    usage.fail(self.name, role)
                    raise LLMAuthError(f"404 from provider: check the base URL and model '{model}'. {r.text[:200]}")
                if r.status_code == 402:
                    usage.fail(self.name, role)
                    raise LLMAuthError(f"402 from provider: the provider account is out of credit. {r.text[:200]}")
                if r.status_code == 429 or r.status_code >= 500:
                    if attempt == 3:
                        usage.fail(self.name, role)
                        raise LLMError(f"{r.status_code} from provider after retries: {r.text[:200]}")
                    ra = r.headers.get("retry-after")
                    delay = float(ra) if ra and ra.replace(".", "", 1).isdigit() else 1.5 * 2 ** attempt + random.random()
                    await asyncio.sleep(min(delay, 30))
                    continue
                if r.status_code != 200:
                    usage.fail(self.name, role)
                    raise LLMError(f"{r.status_code} from provider: {r.text[:300]}")
                data = r.json()
                u = data.get("usage") or {}
                cached = u.get("prompt_cache_hit_tokens") or (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
                usage.add(self.name, model, role, int(u.get("prompt_tokens") or 0), int(cached or 0),
                          int(u.get("completion_tokens") or 0), time.time() - t0)
                try:
                    msg = data["choices"][0]["message"]
                except (KeyError, IndexError):
                    raise LLMError(f"unexpected response shape: {str(data)[:200]}")
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
