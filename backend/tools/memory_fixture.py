"""Offline memory browser fixture. Only runs inside serve_verify's disposable test database."""
import json
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.db.session import session_scope
from app.models import GraphNode, Organization, Project, SimAgent, Simulation
from app.services import jobs
from app.workers import tasks


async def prepare():
    if settings.env != "test" or "kruvim-browser-" not in settings.data_dir:
        raise RuntimeError("Memory fixtures require serve_verify's disposable database")
    async with session_scope() as s:
        org = (await s.execute(select(Organization).order_by(Organization.created_at))).scalars().first()
        project = Project(org_id=org.id, name="Memory verification")
        s.add(project)
        await s.flush()
        pid, oid = project.id, org.id
    records = []
    for name, fresh in (("Prior workout", False), ("Returning workout", False), ("Fresh workout", True)):
        async with session_scope() as s:
            sim = Simulation(org_id=oid, project_id=pid, name=name,
                content={"type": "video", "format": "short_video", "platform": "tiktok", "creator_subject": "gym",
                    "title": "Morning workouts", "text": "Try a quick workout before breakfast. Start gently and keep it comfortable.",
                    "variant_b": {"title": "Workout B", "text": "A gentle morning routine. Warm up and build slowly."}},
                audience={"regions": ["AE", "SA"]}, config={"overrides": {"voice": 20, "crowd": 30, "stakeholders": 1,
                    "hours": 1, "seed": 71, "listening": False, "fresh_audience": fresh, "returning_share": 1 if not fresh else 0}})
            s.add(sim)
            await s.flush()
            sid = sim.id
        await tasks.build_graph({}, sid)
        async with session_scope() as s:
            s.add(GraphNode(simulation_id=sid, key="ent:demo-gym", kind="entity", type="Brand", label="Demo Gym",
                summary="A fictional gym stakeholder."))
        await tasks.prepare_environment({}, sid)
        await tasks.run_simulation({}, sid)
        await jobs.drain()
        async with session_scope() as s:
            sim = await s.get(Simulation, sid)
            if sim.status != "completed" or sim.report_status != "done":
                raise RuntimeError(sim.error or "Memory fixture did not complete")
            agent = (await s.execute(select(SimAgent.ref).where(SimAgent.simulation_id == sid, SimAgent.kind == "voice").limit(1))).scalar_one()
            records.append({"id": sid, "name": name, "agent": agent, "memory": sim.results["agent_memory"]})
    path = Path(__file__).parents[1] / "data/memory-browser.json"
    path.write_text(json.dumps({"project": pid, "runs": records}, indent=2), encoding="utf-8")
    print("Memory browser fixture ready: " + str(path))
