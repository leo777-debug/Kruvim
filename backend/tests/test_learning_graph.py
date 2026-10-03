from unittest.mock import AsyncMock

from app.services.knowledge.learn import learn_round
from app.services.knowledge.store import GraphWriter
from app.services.llm import ProviderSettings, Usage, make_llm


async def test_one_batch_per_round_and_grounded_stances():
    posts = [{"id": 1, "author_ref": "p:1", "content": "Dubai has a useful learning festival."},
             {"id": 2, "author_ref": "p:2", "content": "Dubai does not have a useful learning festival."}]
    writer = GraphWriter("run", 2)
    writer.known.update(["post:1", "post:2", "agent:p:1", "agent:p:2"])
    llm = make_llm(ProviderSettings())
    await learn_round(writer, posts, llm, Usage())
    assert any(n["kind"] == "claim" and n["attributes"]["verified"] is False for n in writer.nodes)
    assert {e["relation"] for e in writer.edges} >= {"asserts", "supports", "opposes"}
    assert all(e["round"] == 2 for e in writer.edges)
    # Live extraction makes one request and rejects fabricated source ids/authors.
    llm.is_dry = False
    llm.complete_json = AsyncMock(return_value={"claims": [{"statement": "A claim", "post_ids": [1], "stances": [
        {"agent": "p:2", "post_id": 1, "relation": "supports"}]},
        {"statement": "Invented", "post_ids": [999], "stances": []}]})
    other = GraphWriter("run", 3)
    other.known.update(writer.known)
    await learn_round(other, posts, llm, Usage())
    llm.complete_json.assert_awaited_once()
    assert len(other.nodes) == 1
    assert [e["relation"] for e in other.edges] == ["asserts"]


async def test_temporal_graph_current_history_and_tenant_access(client, auth):
    from app.services.knowledge.store import snapshot
    headers, _ = auth
    project = (await client.post("/projects", headers=headers, json={"name": "Temporal graph"})).json()
    sim = (await client.post(f"/projects/{project['id']}/simulations", headers=headers,
                            json={"name": "Graph", "content": {"type": "text", "text": "A useful guide"}})).json()
    writer = GraphWriter(sim["id"], 1)
    writer.node("agent:p:1", "agent", "Alice")
    writer.node("claim:one", "claim", "The guide is useful")
    writer.edge("agent:p:1", "claim:one", "supports", "The guide is useful")
    await writer.flush()
    writer.round = 3
    writer.edge("agent:p:1", "claim:one", "opposes", "The guide is useful")
    await writer.flush()
    current = await snapshot(sim["id"])
    history = await snapshot(sim["id"], history=True)
    assert [e["relation"] for e in current["edges"]] == ["opposes"]
    assert len(history["edges"]) == 2
    old = history["edges"][0]
    assert (old["valid_from_round"], old["valid_until_round"]) == (1, 3)
    assert old["valid_until_at"] and old["id"]
    assert [e["relation"] for e in (await snapshot(sim["id"], 2))["edges"]] == ["supports"]
    writer.round = 4
    writer.node("claim:two", "claim", "The guide is misleading")
    writer.edge("claim:two", "claim:one", "contradicts", "The guide is misleading")
    await writer.flush()
    assert [e["relation"] for e in (await snapshot(sim["id"]))["edges"]] == ["contradicts"]
    second = (await client.post("/auth/register", json={"email": "graph-other@example.com", "password": "correct-horse-battery",
                "name": "Other", "org_name": "Other Graph"})).json()
    response = await client.get(f"/simulations/{sim['id']}/graph?history=true", headers={"Authorization": "Bearer " + second["access_token"]})
    assert response.status_code == 404


async def test_hybrid_insight_panorama_and_report_citations(client, auth):
    from app.db.session import session_scope
    from app.models import Simulation
    from app.services.knowledge.store import search
    from app.services.report.agent import generate
    from app.services.report.tools import Toolbox
    headers, data = auth
    project = (await client.post("/projects", headers=headers, json={"name": "Analyst tools"})).json()
    run = (await client.post(f"/projects/{project['id']}/simulations", headers=headers,
                            json={"name": "Learning", "content": {"type": "text", "text": "Python learning"}})).json()
    writer = GraphWriter(run["id"], 0)
    writer.node("topic:python", "entity", "Python learning", summary="Daily useful practice")
    writer.node("agent:student", "agent", "Student", summary="Enjoys useful practice")
    writer.edge("agent:student", "topic:python", "supports", "Daily useful practice helps learning")
    await writer.flush()
    writer.round = 2
    writer.edge("agent:student", "topic:python", "opposes", "Daily useful practice helps learning")
    await writer.flush()
    org = data["orgs"][0]["id"]
    current = await search(run["id"], "Python", hops=1, org_id=org)
    assert {n["key"] for n in current["nodes"]} == {"topic:python", "agent:student"}
    assert [e["relation"] for e in current["facts"]] == ["opposes"]
    assert not (await search(run["id"], "Python", org_id="other-workspace"))["nodes"]
    async with session_scope() as s:
        sim = await s.get(Simulation, run["id"])
        sim.card = {"title": "Python learning"}
        sim.results = {"score": {"mean": 7, "first_impression": 6}}
    tb = Toolbox(sim, make_llm(ProviderSettings()), Usage())
    panorama = await tb.t_panorama_search({"query": "Python"})
    assert len(panorama["facts"]) == 2 and panorama["facts"][1]["valid_from_at"]
    insights = await tb.t_insight_search({"query": "Python", "hops": 2})
    assert len(insights["sub_questions"]) == 3
    assert insights["source_edge_ids"] and insights["source_node_ids"]
    tb.llm.is_dry = False
    tb.llm.complete_json = AsyncMock(return_value={"questions": ["Python learning", "useful practice", "student stance"]})
    await tb.t_insight_search({"query": "Why Python?"})
    tb.llm.complete_json.assert_awaited_once()
    report = await generate(run["id"], make_llm(ProviderSettings()), Usage())
    assert "[node:analysis:" in report.summary
    assert all("[node:analysis:" in section["content"] for section in report.sections)
    assert "unverified reference omitted" in tb.cite("Invented [node:does-not-exist]")
