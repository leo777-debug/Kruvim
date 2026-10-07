from app.services.knowledge.personas import enrich_stakeholder, neighbourhoods
from app.services.knowledge.store import GraphWriter


async def test_persona_uses_current_entity_facts_and_signals(client, auth):
    headers, data = auth
    project = (await client.post("/projects", headers=headers, json={"name": "Personas"})).json()
    run = (await client.post(f"/projects/{project['id']}/simulations", headers=headers,
                            json={"content": {"type": "text", "text": "Festival announcement"}})).json()
    writer = GraphWriter(run["id"])
    writer.node("ent:brand", "entity", "Brand", "Brand")
    writer.node("signal:festival", "signal", "Riyadh festival", summary="A local learning event")
    writer.edge("ent:brand", "signal:festival", "sponsors", "Brand sponsors the learning festival")
    await writer.flush()
    near = await neighbourhoods(run["id"], data["orgs"][0]["id"], ["ent:brand"])
    assert near["ent:brand"]["source_edge_ids"]
    st = enrich_stakeholder({"name": "Brand", "stance": "supportive"}, {"label": "Brand", "summary": "Learning business"}, near["ent:brand"])
    assert "Brand sponsors the learning festival" in st["persona"]
    assert st["interests"] == ["Riyadh festival"]
    assert st["voice"] and st["posting_style"] and st["likely_stance"] == "supportive"
    assert not await neighbourhoods(run["id"], "other-org", ["ent:brand"])
