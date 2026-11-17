from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from sqlalchemy import select
from test_live_provider_failures import make_draft

from app.core.config import settings
from app.db.session import session_scope
from app.models import Simulation, TokenCall
from app.services.llm import ProviderSettings, Usage
from app.services.llm.openai_compat import OpenAICompatLLM
from app.services.providers import Resolved
from app.services.watchdog import bounded_job


async def test_low_rate_stage_continues_and_replays_without_duplicate_requests(client, auth, monkeypatch):
    import asyncio

    from app.services import jobs, token_budget
    from app.services.llm import pacing

    headers, account = auth
    sim_id = await make_draft(client, headers)
    now, requests, answers = [100.0], [], []
    clock = SimpleNamespace(monotonic=lambda: now[0])
    monkeypatch.setattr(pacing, 'time', clock)
    monkeypatch.setattr(token_budget, 'time', clock)
    real_sleep = asyncio.sleep

    async def sleep(delay):
        now[0] += delay
        await real_sleep(0)

    monkeypatch.setattr(asyncio, 'sleep', sleep)
    monkeypatch.setattr(settings, 'serverless', True)
    monkeypatch.setattr(settings, 'simulation_max_duration_seconds', 100)
    queue = AsyncMock(return_value='next-invocation')
    monkeypatch.setattr(jobs, 'enqueue', queue)
    config = ProviderSettings(provider='openai', preset='custom', base_url='https://two-per-minute.example/v1',
                              api_key='fake-key', voice_model='test')

    def respond(request):
        import json
        prompt = json.loads(request.content)['messages'][-1]['content']
        requests.append(prompt)
        return httpx.Response(200, headers={'x-ratelimit-limit-req-minute': '2'}, json={
            'choices': [{'message': {'content': prompt}}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 5}})

    @bounded_job
    async def slow_stage(ctx, sim_id):
        work = token_budget.current.get()
        work.res = Resolved(config, 'org', None)
        llm = OpenAICompatLLM(config)
        await llm.client.aclose()
        llm.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        usage = Usage()
        try:
            answers.clear()
            for index in range(3):
                answers.append(await llm.complete(system='Echo', user=f'answer-{index}', role='voice', max_tokens=20,
                                                   json_out=False, usage=usage, operation_key=f'answer:{index}'))
            await work.summarize(usage)
            async with session_scope() as s:
                row = await s.get(Simulation, sim_id)
                row.status = 'completed'
                row.usage = {'simulation': usage.as_dict(config)}
        finally:
            await llm.aclose()

    first = await slow_stage({}, sim_id)
    assert first == {'status': 'continued'}
    assert requests == ['answer-0', 'answer-1']
    assert queue.await_count == 1
    continuation = queue.await_args.kwargs
    assert continuation['_resume_delay'] > 0
    await slow_stage({}, **continuation)
    assert answers == ['answer-0', 'answer-1', 'answer-2']
    assert requests == answers  # Cached responses did not call the provider again.
    async with session_scope() as s:
        row = await s.get(Simulation, sim_id)
        assert row.status == 'completed'
        assert row.usage['simulation']['calls'] == 3
        assert row.usage['simulation']['input_tokens'] == 30
        assert row.usage['simulation']['output_tokens'] == 15
        receipts = (await s.execute(select(TokenCall).where(TokenCall.org_id == account['orgs'][0]['id']))).scalars().all()
        assert len(receipts) == 3 and all(r.status == 'done' for r in receipts)


async def test_agent_reactions_survive_worker_continuation(client, auth, monkeypatch):
    from app.services import jobs
    from app.services.llm import DryRunLLM
    from app.services.llm.errors import StageYield
    from app.workers import tasks

    headers, _ = auth
    sim_id = await make_draft(client, headers)
    await client.post(f'/simulations/{sim_id}/graph', headers=headers)
    await jobs.drain()
    await client.post(f'/simulations/{sim_id}/environment', headers=headers)
    await jobs.drain()
    original = tasks._llm_for
    calls = {'voice': 0, 'yielded': False, 'suspended': False}

    class SlowModel(DryRunLLM):
        is_dry = False

        async def complete(self, **kwargs):
            return '{"entities": [], "claims": []}'

        async def complete_json(self, **kwargs):
            if kwargs['role'] == 'voice':
                if calls['suspended']:
                    raise StageYield()
                if calls['voice'] == 2 and not calls['yielded']:
                    calls['yielded'] = calls['suspended'] = True
                    raise StageYield()
                calls['voice'] += 1
                return {'score': 7, 'quote': 'An actual model test response', 'would_share': 0, 'would_comment': 0}
            return {'actions': [], 'entities': [], 'claims': [], 'memories': []}

    async def resolve(org_id):
        resolved, _ = await original(org_id)
        return resolved, SlowModel(resolved.settings)

    monkeypatch.setattr(tasks, '_llm_for', resolve)
    queue = AsyncMock(return_value='continued-worker')
    monkeypatch.setattr(jobs, 'enqueue', queue)
    result = await tasks.run_simulation({}, sim_id)
    assert result == {'status': 'continued'}
    async with session_scope() as s:
        row = await s.get(Simulation, sim_id)
        assert row.checkpoint and row.status == 'running'
    calls['suspended'] = False
    await tasks.run_simulation({}, sim_id)
    assert calls['voice'] == 10
    final = (await client.get(f'/simulations/{sim_id}', headers=headers)).json()
    assert final['status'] == 'completed', final.get('error')
    assert final['results']['reliability']['fallback_calls'] == 0
