import re

from app.db.session import session_scope
from app.models import GraphEdge, Report
from app.services.knowledge.store import GraphWriter
from app.services.report.citations import present_report, render_section, source_labels


def test_section_numbers_resolve_and_duplicate_sources_are_not_repeated():
    labels = {("node", "analysis:segments"): {"label": "Simulation statistics: audience segments"},
              ("edge", "12"): {"label": "Graph fact: short workouts are preferred"}}
    text = "Score was 7 [node:analysis:segments]. Short workouts appeal [edge:12]. Again [node:analysis:segments]."
    rendered = render_section(text, labels, private=False)
    assert "node:" not in rendered["rendered_content"] and "edge:" not in rendered["rendered_content"]
    assert [s["number"] for s in rendered["sources"]] == [1, 2]
    assert len({s["label"] for s in rendered["sources"]}) == 2
    assert set(map(int, re.findall(r"#source-(\d+)", rendered["rendered_content"]))) == {s["number"] for s in rendered["sources"]}
    assert render_section("[edge:12]", labels)["sources"][0]["number"] == 1


async def test_readable_sources_use_only_the_validated_runs_graph(client, auth):
    headers, session = auth
    project = (await client.post("/projects", headers=headers, json={"name": "Footnotes"})).json()
    run = (await client.post(f"/projects/{project['id']}/simulations", headers=headers,
                           json={"content": {"type": "text", "text": "A guide"}})).json()
    writer = GraphWriter(run["id"], 3)
    writer.node("analysis:segments", "analysis", "simulation stats", tool="simulation_stats", input={"section": "segments"})
    writer.node("claim:workout", "claim", "Riyadh women favour short workouts")
    writer.edge("analysis:segments", "claim:workout", "supports", "Riyadh women favour short workouts")
    await writer.flush()
    async with session_scope() as s:
        from sqlalchemy import select
        edge = (await s.execute(select(GraphEdge).where(GraphEdge.simulation_id == run["id"]))).scalar_one()
        content = f"Audience segments score 7 [node:analysis:segments]. Short workouts appeal [edge:{edge.id}]."
        report = Report(simulation_id=run["id"], title="Audience", summary="Score 7 [node:analysis:segments]",
                        sections=[{"title": "Segments", "content": content}, {"title": "Preferences", "content": content}])
        private = await present_report(s, report, session["orgs"][0]["id"])
        assert private["rendered_sections"][0]["sources"][0]["label"] == "Simulation statistics: audience segments"
        assert private["rendered_sections"][0]["sources"][1]["edge_id"] == edge.id
        public = await present_report(s, report, session["orgs"][0]["id"], private=False)
        assert "node:" not in str(public) and "edge:" not in str(public)
        for section in public["rendered_sections"]:
            assert set(map(int, re.findall(r"#source-(\d+)", section["rendered_content"]))) == {x["number"] for x in section["sources"]}
        assert not await source_labels(s, run["id"], "another-org", [content])
