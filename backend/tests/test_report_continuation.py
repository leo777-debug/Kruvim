from unittest.mock import AsyncMock

from sqlalchemy import select
from test_live_provider_failures import make_draft

from app.db.session import session_scope
from app.models import Report
from app.services.llm import BaseLLM, ProviderSettings, Usage
from app.services.report.agent import _react, generate


async def test_tool_budget_ends_in_plain_markdown_instead_of_more_tool_json():
    llm = BaseLLM(ProviderSettings())
    llm.complete_json = AsyncMock(return_value={'thought': 'Inspect evidence', 'tool': 'simulation_stats', 'input': {}})
    llm.complete = AsyncMock(return_value='The strongest supported conclusion is to shorten the opening. Evidence remains uncertain.')
    toolbox = AsyncMock()
    toolbox.call.return_value = '{"supported_metric": 5}'
    answer, used = await _react(llm, Usage(), toolbox, 'Select evidence tools', 'Write a supported section', AsyncMock(), 2, 2)
    assert len(used) == 2 and answer.startswith('The strongest supported conclusion')
    assert llm.complete_json.await_count == 2
    assert llm.complete.await_count == 1
    assert llm.complete.await_args.kwargs['json_out'] is False
    assert 'supported_metric' in llm.complete.await_args.kwargs['user']


async def test_failed_report_retains_completed_sections_and_its_outline(client, auth, monkeypatch):
    from app.services import jobs
    from app.services.report import agent
    headers, _ = auth
    sim_id = await make_draft(client, headers)
    await client.post(f'/simulations/{sim_id}/autopilot', headers=headers)
    await jobs.drain()
    async with session_scope() as s:
        report = (await s.execute(select(Report).where(Report.simulation_id == sim_id)
                                  .order_by(Report.created_at.desc()))).scalars().first()
        report.status, report.model, report.title, report.summary = 'failed', 'report-model', 'Retried report', 'Existing summary'
        report.outline = [{'title': 'Completed section', 'goal': 'A'}, {'title': 'Remaining section', 'goal': 'B'}]
        report.sections = [{'title': 'Completed section', 'content': 'A previously completed model section.', 'tools': []}]
        report_id = report.id
    llm = BaseLLM(ProviderSettings(report_model='report-model'))
    llm.complete_json = AsyncMock(side_effect=AssertionError('The outline must not be requested again'))
    writer = AsyncMock(return_value=('The remaining model section.', []))
    monkeypatch.setattr(agent, '_react', writer)
    monkeypatch.setattr(agent, 'optimize', AsyncMock(return_value=None))
    result = await generate(sim_id, llm, Usage())
    assert result.id == report_id and result.status == 'done'
    assert result.sections[0]['content'] == 'A previously completed model section.'
    assert result.sections[1]['content'].startswith('The remaining model section.')
    assert writer.await_count == 1
    assert llm.complete_json.await_count == 0
