"""Readable, section-local footnotes over raw graph references (including legacy reports)."""
from __future__ import annotations

import re

from sqlalchemy import select

from app.models import GraphEdge, GraphNode, Post, Simulation

REF = re.compile(r"\[(node|edge):([^\]]+)\]")
RAW = re.compile(r"\b(?:node|edge):[^\s\]\)<>]+")


def clean(text):
    return RAW.sub("source", str(text or ""))


def render_section(content, labels, private=True):
    sources, numbers = [], {}

    def reference(match):
        key = (match[1], match[2])
        if key not in numbers:
            numbers[key] = len(sources) + 1
            source = {"number": numbers[key], "label": clean(labels.get(key, {}).get("label", "Simulation evidence"))}
            if private:
                source.update({"kind": key[0], "id": key[1], **{k: v for k, v in labels.get(key, {}).items() if k != "label"}})
            sources.append(source)
        return f"[{numbers[key]}](#source-{numbers[key]})"

    # Legacy appended evidence becomes inline footnotes rather than a technical paragraph.
    content = re.sub(r"\n\s*Evidence:\s*", " ", str(content or ""))
    content = REF.sub(reference, content)
    content = clean(content)
    if sources:
        content += "\n\n### Sources\n\n" + "\n".join(f"{s['number']}. {s['label']}" for s in sources)
    return {"rendered_content": content, "sources": sources}


async def source_labels(s, sim_id, org_id, texts):
    # Both ids are supplied by the validated run; never resolve a reference in another workspace/run.
    if not (await s.execute(select(Simulation.id).where(Simulation.id == sim_id, Simulation.org_id == org_id))).scalar_one_or_none():
        return {}
    references = {tuple(m.groups()) for text in texts for m in REF.finditer(text or "")}
    node_keys = {key for kind, key in references if kind == "node"}
    edge_ids = [int(key) for kind, key in references if kind == "edge" and key.isdigit()]
    edges = (await s.execute(select(GraphEdge).where(GraphEdge.simulation_id == sim_id, GraphEdge.id.in_(edge_ids)))).scalars().all()
    node_keys.update(e.dst for e in edges)
    nodes = (await s.execute(select(GraphNode).where(GraphNode.simulation_id == sim_id, GraphNode.key.in_(node_keys)))).scalars().all()
    post_ids = [int(n.key[5:]) for n in nodes if n.key.startswith("post:") and n.key[5:].isdigit()]
    posts = {p.id: p for p in (await s.execute(select(Post).where(Post.simulation_id == sim_id, Post.id.in_(post_ids)))).scalars()}
    labels = {}
    for node in nodes:
        attrs = node.attributes or {}
        label = clean(node.label)
        target = {"node_id": node.key}
        if node.kind == "analysis":
            tool = attrs.get("tool", "analysis").replace("_", " ").capitalize()
            section = (attrs.get("input") or {}).get("section")
            if not section and isinstance(attrs.get("observation"), dict):
                section = "segments" if "by_region" in attrs["observation"] else None
            detail = {"segments": "audience segments", "overview": "overview", "attention": "attention retention",
                      "discourse": "conversation", "spread": "reach", "ab": "variant comparison"}.get(section, section)
            label = ("Simulation statistics" if tool == "Simulation stats" else tool) + (f": {detail}" if detail else "")
        elif node.key.startswith("post:") and node.key[5:].isdigit() and int(node.key[5:]) in posts:
            post = posts[int(node.key[5:])]
            label = f"Post by {clean(post.author_name)}, round {post.round}"
        elif node.kind == "claim":
            label = "Graph claim: " + clean(node.summary or node.label)[:180]
        if node.kind == "agent" and node.key.startswith("agent:"):
            target["agent_ref"] = node.key[6:]
        labels[("node", node.key)] = {"label": label, **target}
    for edge in edges:
        labels[("edge", str(edge.id))] = {"label": "Graph fact: " + clean(edge.fact or edge.relation.replace("_", " "))[:180],
                                            "node_id": edge.dst, "edge_id": edge.id}
    return labels


async def present_report(s, report, org_id, private=True):
    sections = list(report.sections or [])
    # Imported/legacy reports may have Markdown but no structured sections.
    if not sections:
        chunks = re.split(r"(?m)^## ", report.markdown or "")
        summary = re.sub(r"(?m)^# .*\n?", "", chunks[0]).strip() or report.summary
        sections = [{"title": chunk.partition("\n")[0], "content": chunk.partition("\n")[2]} for chunk in chunks[1:]]
    else:
        summary = report.summary
    from app.services.population.uae import notice
    sim = (await s.execute(select(Simulation).where(Simulation.id == report.simulation_id, Simulation.org_id == org_id))).scalar_one_or_none()
    if sim:
        sections.append({"title": "Audience sources and limitations", "content": notice((sim.config or {}).get("population_provenance"))})
    labels = await source_labels(s, report.simulation_id, org_id, [summary, *[x.get("content", "") for x in sections]])
    intro = render_section(summary, labels, private)
    rendered = [{**({"title": clean(x["title"]), "content": x.get("content", "")} if private else {"title": clean(x["title"])}),
                 **render_section(x.get("content", ""), labels, private)} for x in sections]
    markdown = f"# {clean(report.title)}\n\n{intro['rendered_content']}\n\n" + "\n\n".join(
        f"## {x['title']}\n\n{x['rendered_content']}" for x in rendered)
    return {"rendered_summary": intro["rendered_content"], "summary_sources": intro["sources"],
            "rendered_sections": rendered, "rendered_markdown": markdown}
