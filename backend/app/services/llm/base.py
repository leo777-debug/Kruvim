"""Provider-neutral LLM interface, usage accounting and tolerant JSON parsing."""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field

from app.core.metrics import LLM_CALLS, LLM_TOKENS


class LLMError(Exception):
    """A single call failed (bad JSON, refusal, transient error after retries)."""


class LLMAuthError(LLMError):
    """Configuration problem (bad key, unknown model, unreachable endpoint): abort the job."""


@dataclass
class ProviderSettings:
    provider: str = "dryrun"
    preset: str = "dryrun"
    base_url: str = ""
    api_key: str = ""
    voice_model: str = ""
    report_model: str = ""
    vision_model: str = ""
    concurrency: int = 6
    temperature: float = 0.9
    json_mode: bool = True
    timeout: float = 120.0
    price_in: float | None = None
    price_cached: float | None = None
    price_out: float | None = None


@dataclass
class Usage:
    calls: int = 0
    failed: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    by_role: dict = field(default_factory=dict)

    def add(self, provider: str, model: str, role: str, inp: int, cached: int, out: int, secs: float):
        self.calls += 1
        self.input_tokens += inp
        self.cached_tokens += cached
        self.output_tokens += out
        self.seconds += secs
        r = self.by_role.setdefault(role, {"calls": 0, "input": 0, "cached": 0, "output": 0, "model": model})
        r["calls"] += 1
        r["input"] += inp
        r["cached"] += cached
        r["output"] += out
        LLM_CALLS.labels(provider, role, "ok").inc()
        LLM_TOKENS.labels(provider, "input").inc(inp)
        LLM_TOKENS.labels(provider, "output").inc(out)

    def fail(self, provider: str, role: str):
        self.failed += 1
        LLM_CALLS.labels(provider, role, "error").inc()

    def cost(self, s: ProviderSettings) -> float | None:
        if s.price_in is None or s.price_out is None:
            return None
        pc = s.price_cached if s.price_cached is not None else s.price_in
        unc = max(0, self.input_tokens - self.cached_tokens)
        embedding = self.by_role.get("retrieval_embedding", {})
        if embedding and embedding.get("cost_usd") is None:
            return None
        unc = max(0, unc - embedding.get("input", 0))
        return round((unc * s.price_in + self.cached_tokens * pc + self.output_tokens * s.price_out) / 1e6 + embedding.get("cost_usd", 0), 5)

    def as_dict(self, s: ProviderSettings | None = None) -> dict:
        return {"calls": self.calls, "failed": self.failed, "input_tokens": self.input_tokens,
                "cached_tokens": self.cached_tokens, "output_tokens": self.output_tokens,
                "seconds": round(self.seconds, 1), "by_role": self.by_role,
                "cost_usd": self.cost(s) if s else None}


_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def extract_json(text: str):
    """First JSON object/array in a reply; tolerates <think> blocks, code fences, prose and trailing commas."""
    if not text:
        raise ValueError("empty reply")
    t = _THINK.sub("", text).strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I | re.M).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    start = next((i for i, ch in enumerate(t) if ch in "{["), None)
    if start is None:
        raise ValueError("no JSON object in reply")
    open_ch = t[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth, in_str, esc = 0, False, False
    for j in range(start, len(t)):
        c = t[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                frag = re.sub(r",\s*([}\]])", r"\1", t[start:j + 1])
                return json.loads(frag)
    raise ValueError("unterminated JSON in reply")


ROLE_MODEL = {"report": "report_model", "content": "report_model", "brief": "report_model", "config": "report_model",
              "ontology": "report_model", "extract": "report_model", "vision": "vision_model"}


class BaseLLM:
    name = "base"
    is_dry = False

    def __init__(self, s: ProviderSettings):
        self.s = s
        self.sem = asyncio.Semaphore(max(1, int(s.concurrency or 1)))

    def model_for(self, role: str) -> str:
        attr = ROLE_MODEL.get(role, "voice_model")
        m = getattr(self.s, attr) or ""
        if not m and attr != "vision_model":
            m = self.s.report_model or self.s.voice_model
        return m

    def has_vision(self) -> bool:
        return bool(self.s.vision_model)

    async def complete(self, *, system: str, user: str, role: str, max_tokens: int, usage: Usage,
                       json_out: bool = True, images: list | None = None, temperature: float | None = None) -> str:
        raise NotImplementedError

    async def complete_json(self, *, system: str, user: str, role: str, max_tokens: int, usage: Usage,
                            images: list | None = None, temperature: float | None = None):
        prompt = user
        last: Exception | None = None
        for _ in range(2):
            text = await self.complete(system=system, user=prompt, role=role, max_tokens=max_tokens, usage=usage,
                                       json_out=True, images=images, temperature=temperature)
            try:
                return extract_json(text)
            except Exception as exc:
                last = exc
                prompt = user + "\n\nYour previous reply could not be parsed. Reply with ONE valid JSON object and nothing else."
        usage.fail(self.name, role)
        raise LLMError(f"model did not return valid JSON: {last}")

    async def list_models(self) -> list[str]:
        return []

    async def aclose(self) -> None:
        pass
