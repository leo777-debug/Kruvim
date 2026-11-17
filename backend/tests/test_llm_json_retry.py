from unittest.mock import AsyncMock

import pytest

from app.services.llm.base import BaseLLM, CompletionText, LLMError, ProviderSettings, Usage


async def test_unfinished_analyst_section_cannot_be_marked_complete():
    from app.services.report.agent import _react
    llm = BaseLLM(ProviderSettings())
    llm.complete_json = AsyncMock(return_value={"thought": "Still thinking"})
    with pytest.raises(LLMError, match="did not finish"):
        await _react(llm, Usage(), None, "Return a final section", "Evidence", AsyncMock(), 0, 2)


@pytest.mark.parametrize(("initial", "retry"), [(64, 128), (5000, 8192), (10000, 10000)])
async def test_incomplete_json_retries_with_room_without_accepting_partial_output(initial, retry):
    llm = BaseLLM(ProviderSettings())
    llm.complete = AsyncMock(side_effect=['{"final": "an unfinished answer', '{"final": "A complete answer"}'])
    result = await llm.complete_json(system="Return a final answer", user="Evidence remains unchanged", role="report",
                                     max_tokens=initial, usage=Usage())
    assert result == {"final": "A complete answer"}
    assert llm.complete.await_args_list[0].kwargs["max_tokens"] == initial
    assert llm.complete.await_args_list[1].kwargs["max_tokens"] == retry
    assert llm.complete.await_args_list[1].kwargs["user"].startswith("Evidence remains unchanged")


async def test_two_incomplete_outputs_still_fail_instead_of_fabricating_a_report():
    llm = BaseLLM(ProviderSettings())
    llm.complete = AsyncMock(return_value='{"final": "unfinished')
    usage = Usage()
    with pytest.raises(LLMError, match="unterminated"):
        await llm.complete_json(system="Report", user="Evidence", role="report", max_tokens=100, usage=usage)
    assert llm.complete.await_count == 2 and usage.failed == 1


async def test_provider_output_limit_also_retries_even_when_partial_json_would_parse():
    llm = BaseLLM(ProviderSettings())
    llm.complete = AsyncMock(side_effect=[CompletionText('{"final":"Cut off"}', truncated=True), '{"final":"Complete."}'])
    result = await llm.complete_json(system="Report", user="Evidence", role="report", max_tokens=2200, usage=Usage())
    assert result["final"] == "Complete."
    assert llm.complete.await_args_list[1].kwargs["max_tokens"] == 4400


async def test_openai_compatible_adapter_does_not_accept_a_length_limited_json_object():
    import httpx

    from app.services.llm.openai_compat import OpenAICompatLLM
    calls = []

    def respond(request):
        import json
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "length" if len(calls) == 1 else "stop",
            "message": {"content": '{"final":"Cut off"}' if len(calls) == 1 else '{"final":"Complete."}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20}})

    llm = OpenAICompatLLM(ProviderSettings(provider="openai", base_url="https://model.example/v1", report_model="test"))
    await llm.client.aclose()
    llm.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    usage = Usage()
    try:
        result = await llm.complete_json(system="Report", user="Evidence", role="report", max_tokens=2200, usage=usage)
    finally:
        await llm.aclose()
    assert result == {"final": "Complete."} and [call["max_tokens"] for call in calls] == [2200, 4400]
    assert usage.calls == 2  # Both upstream responses remain accounted for.


async def test_output_limit_metadata_survives_receipt_replay_without_another_upstream_call(auth, monkeypatch):
    from app.services import token_budget
    from app.services.providers import Resolved

    monkeypatch.setattr(token_budget, "provider_status", AsyncMock())
    settings = ProviderSettings(provider="openai", report_model="test")
    llm = BaseLLM(settings)
    work = token_budget.Work(auth[1]["orgs"][0]["id"], None, "truncated-replay", Resolved(settings, "org", None))

    async def upstream(_, **kwargs):
        kwargs["usage"].add("openai", "test", "report", 10, 0, 20, 0)
        return CompletionText('{"final":"Cut off"}', truncated=True)

    call = AsyncMock(side_effect=upstream)
    kwargs = {"system": "Report", "user": "Evidence", "role": "report", "max_tokens": 2200, "usage": Usage()}
    first = await work.call(llm, call, kwargs, "attempt-0")
    replay = await work.call(llm, call, kwargs, "attempt-0")
    assert first.truncated and replay.truncated and replay == first
    assert call.await_count == 1
