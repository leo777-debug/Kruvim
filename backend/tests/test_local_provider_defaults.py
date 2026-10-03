import json

import httpx

from app.core.config import Settings
from app.services.llm import ProviderSettings, Usage, make_llm


async def test_blank_keys_and_keyless_local_model_requests():
    assert Settings.model_fields["llm_api_key"].default == ""
    assert ProviderSettings().api_key == ""
    settings = ProviderSettings(provider="openai", preset="ollama", base_url="http://local-model.test/v1",
                                voice_model="local-small", report_model="local-small")
    llm = make_llm(settings)
    headers = dict(llm.client.headers)
    await llm.client.aclose()
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}],
                                       "usage": {"prompt_tokens": 2, "completion_tokens": 3}})

    llm.client = httpx.AsyncClient(headers=headers, transport=httpx.MockTransport(respond))
    try:
        assert await llm.complete_json(system="Return JSON", user="Local test", role="extract", max_tokens=32,
                                       usage=Usage()) == {"ok": True}
        assert "authorization" not in requests[0].headers
        assert json.loads(requests[0].content)["model"] == "local-small"
    finally:
        await llm.client.aclose()
