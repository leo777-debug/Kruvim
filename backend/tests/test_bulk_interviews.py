import asyncio
from unittest.mock import AsyncMock

from sqlalchemy import func, select

from app.db.session import session_scope
from app.models import Organization, SimAgent, SimEvent, Simulation, Survey
from app.services.interaction.interview import survey
from app.services.interaction.selection import survey_estimate
from app.services.llm import LLMAuthError, ProviderSettings, Usage, make_llm
from app.services.providers import Resolved
from app.workers.tasks import run_survey


async def test_every_voice_preview_progress_and_idempotent_worker(client, auth, monkeypatch):
    headers, _ = auth
    project = (await client.post("/projects", headers=headers, json={"name": "Bulk interviews"})).json()
    run = (await client.post(f"/projects/{project['id']}/simulations", headers=headers,
                            json={"content": {"type": "text", "text": "Daily Python practice"}})).json()
    async with session_scope() as s:
        sim = await s.get(Simulation, run["id"])
        sim.status = "completed"
        sim.card = {"title": "Practice"}
        for i in range(55):
            s.add(SimAgent(simulation_id=sim.id, ref=f"p:{i}", kind="voice", name=f"Person {i}", handle=f"person{i}", region="SA",
                           persona={"stance": "enthusiast"}, state={"opinion": 7.0}))
        s.add(SimAgent(simulation_id=sim.id, ref="s:brand", kind="stakeholder", name="Brand", handle="brand", region="AE", persona={}))
    monkeypatch.setattr("app.services.jobs.enqueue", AsyncMock(return_value="survey-job"))
    body = {"question": "Would you use this?", "everyone": True, "region": "AE"}
    estimate = (await client.post(f"/simulations/{sim.id}/surveys/estimate", headers=headers, json=body)).json()
    assert estimate["respondents"] == 55 and estimate["credits"] == 0 and estimate["dry"]
    assert (await client.post(f"/simulations/{sim.id}/surveys", headers=headers, json=body)).status_code == 409
    created = await client.post(f"/simulations/{sim.id}/surveys", headers=headers,
        json={**body, "confirmed_count": 55, "confirmed_credits": 0})
    assert created.status_code == 200, created.text
    survey_id = created.json()["id"]
    await run_survey({}, survey_id)
    async with session_scope() as s:
        sv = await s.get(Survey, survey_id)
        assert sv.status == "done" and len(sv.answers) == 55
        assert all(a["agent"].startswith("p:") for a in sv.answers)
        assert '"themes"' in sv.summary
        count = (await s.execute(select(func.count()).select_from(SimEvent).where(SimEvent.simulation_id == sim.id))).scalar()
    await run_survey({}, survey_id)
    async with session_scope() as s:
        after = (await s.execute(select(func.count()).select_from(SimEvent).where(SimEvent.simulation_id == sim.id))).scalar()
        assert after == count
    estimates = survey_estimate(2000, 2000, Resolved(ProviderSettings(provider="openai"), "platform", None), 3000)
    assert estimates["model_calls"] == 2041 and estimates["max_credits"] == 2082
    platform = Resolved(ProviderSettings(provider="openai"), "platform", None)
    monkeypatch.setattr("app.api.routes.simulations.resolve", AsyncMock(return_value=platform))
    monkeypatch.setattr("app.workers.tasks._llm_for", AsyncMock(side_effect=LLMAuthError("Provider unavailable")))
    async with session_scope() as s:
        org = await s.get(Organization, sim.org_id)
        before = org.credits_balance
    paid = await client.post(f"/simulations/{sim.id}/surveys", headers=headers,
        json={**body, "confirmed_count": 55, "confirmed_credits": 61})
    assert paid.status_code == 200, paid.text
    async with session_scope() as s:
        org = await s.get(Organization, sim.org_id)
        assert org.credits_balance == before - 61
    await run_survey({}, paid.json()["id"])
    async with session_scope() as s:
        org = await s.get(Organization, sim.org_id)
        failed = await s.get(Survey, paid.json()["id"])
        assert org.credits_balance == before and failed.status == "failed"
        assert failed.filters["reserved_credits"] == 0


async def test_hierarchical_summary_and_bounded_concurrency():
    llm = make_llm(ProviderSettings(concurrency=3))
    llm.is_dry = False
    active, peak = 0, 0
    async def complete(**kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.001)
        active -= 1
        return "I would practice daily."
    llm.complete = complete
    llm.complete_json = AsyncMock(return_value={"themes": [{"theme": "Useful practice", "count": 55, "quote": "I would practice daily."}], "takeaway": "Use a concrete example."})
    details = [{"ref": f"p:{i}", "name": str(i), "persona": {}, "state": {"opinion": 7}} for i in range(55)]
    progress = AsyncMock()
    out = await survey(details, {}, "youtube", "Would you practice?", llm, Usage(), progress)
    assert len(out["answers"]) == 55 and peak <= 3
    assert progress.await_count == 55
    assert llm.complete_json.await_count == 3
