"""Stakeholder personas grounded in a tenant's current graph neighbourhood."""
from sqlalchemy import or_, select

from app.db.session import session_scope
from app.models import GraphEdge, GraphNode, Simulation


async def neighbourhoods(sim_id: str, org_id: str, keys: list[str]) -> dict:
    async with session_scope() as s:
        if not (await s.execute(select(Simulation.id).where(Simulation.id == sim_id, Simulation.org_id == org_id))).scalar():
            return {}
        edges = (await s.execute(select(GraphEdge).where(GraphEdge.simulation_id == sim_id,
                    GraphEdge.valid_until_round.is_(None), or_(GraphEdge.src.in_(keys), GraphEdge.dst.in_(keys)))
                    .order_by(GraphEdge.id).limit(2000))).scalars().all()
        related = set(keys) | {k for e in edges for k in (e.src, e.dst)}
        nodes = {n.key: n for n in (await s.execute(select(GraphNode).where(GraphNode.simulation_id == sim_id,
                    GraphNode.key.in_(related)))).scalars()}
    out = {}
    for key in keys:
        links = [e for e in edges if key in (e.src, e.dst)][:24]
        near = [nodes[k] for k in sorted({k for e in links for k in (e.src, e.dst)} - {key}) if k in nodes]
        out[key] = {"related": [{"key": n.key, "label": n.label, "kind": n.kind, "summary": n.summary[:400]} for n in near],
                    "facts": [{"id": e.id, "relation": e.relation, "fact": e.fact, "source": e.src, "target": e.dst} for e in links],
                    "source_node_ids": [key, *[n.key for n in near]], "source_edge_ids": [e.id for e in links]}
    return out


def enrich_stakeholder(st: dict, entity: dict, neighbourhood: dict) -> dict:
    facts = [x["fact"] for x in neighbourhood.get("facts", []) if x.get("fact")][:5]
    interests = [x["label"] for x in neighbourhood.get("related", []) if x["kind"] in ("entity", "claim", "signal")][:8]
    voice = str(st.get("voice") or "Measured, specific and consistent with the account's public role.")[:500]
    style = str(st.get("posting_style") or "Short factual posts; explain interests and cite related events before responding to criticism.")[:500]
    stance = str(st.get("likely_stance") or st.get("stance") or "neutral")[:500]
    description = str(st.get("persona") or entity.get("summary") or "")[:2000]
    description += "\nVoice: " + voice + "\nPosting style: " + style + "\nLikely stance: " + stance
    if interests:
        description += "\nInterests: " + "; ".join(interests)
    if facts:
        description += "\nGraph context (observations, not verified truth): " + " ".join(facts)
    return {**st, "entity": entity["label"], "persona": description, "voice": voice,
            "interests": st.get("interests") if isinstance(st.get("interests"), list) else interests,
            "likely_stance": stance, "posting_style": style, "graph_context": neighbourhood}
