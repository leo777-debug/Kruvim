from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.session import session_scope
from app.models import Report
from app.models.cloud import CloudJob
from app.services.llm import DryRunLLM, ProviderSettings, Usage
from app.services.llm.errors import ProviderFailure, classify
from app.services.llm.openai_compat import OpenAICompatLLM


async def test_provider_error_preserves_safe_category_and_http_status():
    config = ProviderSettings(provider="openai", preset="custom", base_url="https://provider.example/v1",
                              api_key="never-print-this-secret", voice_model="test")
    llm = OpenAICompatLLM(config)
    await llm.client.aclose()
    llm.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(402,
        json={"error": {"message": "never-print-this-secret: insufficient credit"}})))
    usage = Usage()
    try:
        with pytest.raises(ProviderFailure) as caught:
            await llm.complete(system="Reply OK", user="OK", role="voice", max_tokens=5, json_out=False, usage=usage)
        assert caught.value.category == "quota_exhausted"
        assert "HTTP 402" in str(caught.value)
        assert "never-print-this-secret" not in str(caught.value)
        assert "never-print-this-secret" not in repr(config)
        assert usage.failed == 1 and usage.calls == 0
    finally:
        await llm.aclose()


async def test_throttled_adapter_observes_retry_after_before_retry(monkeypatch):
    from app.services.llm import pacing
    now = [100.0]
    requests = []
    monkeypatch.setattr(pacing.time, "monotonic", lambda: now[0])

    async def sleep(delay):
        now[0] += delay

    monkeypatch.setattr(pacing.asyncio, "sleep", sleep)

    def respond(request):
        requests.append(now[0])
        if len(requests) == 1:
            return httpx.Response(429, headers={"retry-after": "30", "x-ratelimit-limit-req-minute": "2"},
                                  json={"error": {"message": "Too many requests"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}],
                                        "usage": {"prompt_tokens": 2, "completion_tokens": 1}})

    llm = OpenAICompatLLM(ProviderSettings(provider="openai", base_url="https://throttled.example/v1",
                                          api_key="fake-key", voice_model="test"))
    await llm.client.aclose()
    llm.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        usage = Usage()
        assert await llm.complete(system="Reply OK", user="OK", role="voice", max_tokens=5, json_out=False, usage=usage) == "OK"
        assert requests[1] - requests[0] >= 30
        assert usage.calls == 1 and usage.failed == 0
        assert llm.rate_limits["x-ratelimit-limit-req-minute"] == "2"
    finally:
        await llm.aclose()


async def make_draft(client, headers):
    project = (await client.post("/projects", headers=headers, json={"name": "Strict live verification"})).json()
    response = await client.post(f"/projects/{project['id']}/simulations", headers=headers, json={
        "content": {"type": "video", "transcript": "Reset your desk: sort papers, clear unused tools and start work."},
        "audience": {"regions": ["AE"]},
        "overrides": {"voice": 10, "crowd": 20, "stakeholders": 0, "hours": 1, "listening": False},
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def install_failed_model(monkeypatch):
    from app.workers import tasks
    original = tasks._llm_for

    class FailedModel(DryRunLLM):
        is_dry = False

        async def complete(self, **kwargs):
            kwargs["usage"].fail("custom", kwargs["role"])
            raise ProviderFailure(classify(429, settings=self.s))

    async def resolve(org_id):
        resolved, _ = await original(org_id)
        return resolved, FailedModel(resolved.settings)

    monkeypatch.setattr(tasks, "_llm_for", resolve)


async def test_environment_failure_cannot_advance_with_deterministic_configuration(client, auth, monkeypatch):
    from app.services.jobs import drain
    headers, _ = auth
    sim_id = await make_draft(client, headers)
    await client.post(f"/simulations/{sim_id}/graph", headers=headers)
    await drain()
    await install_failed_model(monkeypatch)
    await client.post(f"/simulations/{sim_id}/environment", headers=headers)
    await drain()
    result = (await client.get(f"/simulations/{sim_id}", headers=headers)).json()
    assert result["status"] == "failed"
    assert "HTTP 429" in result["error"] and "rate limiting" in result["error"]
    assert not result["results"]


async def test_report_failure_is_not_replaced_by_dry_outline_and_cloud_job_is_error(client, auth, monkeypatch):
    from app.services.jobs import drain
    headers, _ = auth
    sim_id = await make_draft(client, headers)
    await client.post(f"/simulations/{sim_id}/autopilot", headers=headers)
    await drain()
    await install_failed_model(monkeypatch)
    monkeypatch.setattr(settings, "cron_secret", "local-test-scheduler")
    async with session_scope() as s:
        job = CloudJob(name="generate_report", payload={"sim_id": sim_id})
        s.add(job)
        await s.flush()
        job_id = job.id
    response = await client.post(f"/internal/jobs/{job_id}", headers={"Authorization": "Bearer local-test-scheduler"})
    assert response.status_code == 200
    assert response.json()["status"] == "error"
    result = (await client.get(f"/simulations/{sim_id}", headers=headers)).json()
    assert result["report_status"] == "failed"
    assert result["usage"]["report"]["failed"] == 1
    async with session_scope() as s:
        assert (await s.get(CloudJob, job_id)).status == "error"
        failed = (await s.execute(select(Report).where(Report.simulation_id == sim_id, Report.status == "failed"))).scalars().all()
        assert failed and "HTTP 429" in failed[-1].error


async def test_live_graph_extraction_never_substitutes_dry_entities():
    from app.services.knowledge.build import DEFAULT_ONTOLOGY, extract
    llm = DryRunLLM(ProviderSettings())
    llm.is_dry = False
    llm.complete_json = AsyncMock(side_effect=ProviderFailure(classify(503)))
    with pytest.raises(ProviderFailure):
        await extract("Any text", DEFAULT_ONTOLOGY, llm, Usage(), [])
