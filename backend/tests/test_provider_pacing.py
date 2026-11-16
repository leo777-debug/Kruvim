import httpx
import pytest

from app.services.llm import pacing


async def test_shared_gate_respects_provider_minute_limit(monkeypatch):
    now = [100.0]
    sleeps = []
    monkeypatch.setattr(pacing.time, 'monotonic', lambda: now[0])

    async def sleep(delay):
        sleeps.append(delay)
        now[0] += delay

    monkeypatch.setattr(pacing.asyncio, 'sleep', sleep)
    first = pacing.for_provider('https://provider.test/v1', 'fake-key')
    second = pacing.for_provider('https://provider.test/v1', 'fake-key')
    assert first is second
    assert pacing.for_provider('https://provider.test/v1', 'other-key') is not first
    await first.wait()
    first.observe(httpx.Response(200, headers={'x-ratelimit-limit-req-minute': '2'}))
    await second.wait()
    assert sleeps == pytest.approx([30.1])
    assert first.interval == 30.1


async def test_rate_limit_without_retry_header_cools_down(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(pacing.time, 'monotonic', lambda: now[0])

    async def sleep(delay):
        now[0] += delay

    monkeypatch.setattr(pacing.asyncio, 'sleep', sleep)
    gate = pacing.Gate()
    gate.observe(httpx.Response(429))
    await gate.wait()
    assert now[0] == 160
    gate.observe(httpx.Response(429, headers={'retry-after': '90'}))
    await gate.wait()
    assert now[0] == 250
