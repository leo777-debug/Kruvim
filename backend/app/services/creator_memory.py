"""A bounded, resettable workspace history; observations remain attributed to simulations."""
from sqlalchemy import select

from app.db.base import utcnow
from app.db.session import session_scope
from app.models import Organization, Simulation


async def update_memory(org_id, sim_id):
    async with session_scope() as s:
        sim = (await s.execute(select(Simulation).where(Simulation.id == sim_id, Simulation.org_id == org_id))).scalar_one()
        org = (await s.execute(select(Organization).where(Organization.id == org_id).with_for_update())).scalar_one()
        memory = dict((org.settings or {}).get("creator_memory", {}))
        observations = [x for x in memory.get("observations", []) if x["simulation_id"] != sim_id]
        result = sim.results or {}
        observations.append({"simulation_id": sim_id, "title": sim.name, "score": result.get("score", {}).get("mean"),
            "format": sim.content.get("format"), "topics": sim.card.get("topic_labels", []),
            "drivers": result.get("psychology", {}).get("drivers", [])[:3],
            "objections": result.get("psychology", {}).get("objections", [])[:3],
            "hook": sim.card.get("hook"), "completion": result.get("heatmap", {}).get("completion"),
            "dry": result.get("provider", {}).get("dry", True)})
        observations = observations[-20:]
        summary = "; ".join(f"{x['title']}: opinion {x['score']}/10, drivers " + ", ".join(d.get("driver", "") for d in x["drivers"])
                            for x in observations[-5:])[:1800]
        memory = {**memory, "observations": observations, "summary": summary, "updated_at": utcnow().isoformat(),
                  "note": "Learned from simulated reactions; use linked real outcomes to evaluate accuracy."}
        org.settings = {**(org.settings or {}), "creator_memory": memory}
