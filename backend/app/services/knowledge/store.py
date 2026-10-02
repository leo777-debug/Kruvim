"""Knowledge graph persistence + live streaming of graph deltas."""
from __future__ import annotations

import re

from sqlalchemy import and_, or_, select

from app.db.session import session_scope
from app.models import GraphEdge, GraphNode
from app.services.events import bus


def slug(s: str) -> str:
    return re.sub(r"[^\w؀-ۿ]+", "-", (s or "").strip().lower()).strip("-")[:120] or "x"


class GraphWriter:
    """Buffers nodes/edges for one simulation, de-duplicates by key, flushes to DB and emits
    `graph.delta` events so every client watching the graph sees it grow."""

    def __init__(self, sim_id: str, round_: int = -1):
        self.sim_id = sim_id
        self.round = round_
        self.known: set[str] = set()
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.edge_keys: set[tuple] = set()

    async def load_existing(self):
        async with session_scope() as s:
            self.known = {k for (k,) in (await s.execute(select(GraphNode.key).where(GraphNode.simulation_id == self.sim_id))).all()}
            self.edge_keys = {(a, b, r) for a, b, r in (await s.execute(select(GraphEdge.src, GraphEdge.dst, GraphEdge.relation)
                                                                       .where(GraphEdge.simulation_id == self.sim_id))).all()}

    def node(self, key: str, kind: str, label: str, type_: str = "", summary: str = "", **attrs) -> str:
        if key not in self.known:
            self.known.add(key)
            self.nodes.append({"key": key, "kind": kind, "type": type_ or kind, "label": label[:300], "summary": summary[:2000],
                               "attributes": attrs, "round": self.round})
        return key

    def edge(self, src: str, dst: str, relation: str, fact: str = "", weight: float = 1.0, **attrs) -> None:
        if src == dst and relation not in ("self",):
            return
        k = (src, dst, relation)
        if k in self.edge_keys:
            return
        self.edge_keys.add(k)
        self.edges.append({"src": src, "dst": dst, "relation": relation, "fact": fact[:1000], "weight": weight,
                           "attributes": attrs, "round": self.round})

    async def flush(self, note: str | None = None) -> int:
        if not self.nodes and not self.edges:
            return 0
        nodes, edges = self.nodes, [e for e in self.edges if e["src"] in self.known and e["dst"] in self.known]
        self.nodes, self.edges = [], []
        async with session_scope() as s:
            for n in nodes:
                s.add(GraphNode(simulation_id=self.sim_id, key=n["key"], kind=n["kind"], type=n["type"], label=n["label"],
                                summary=n["summary"], attributes=n["attributes"], round=n["round"]))
            for e in edges:
                s.add(GraphEdge(simulation_id=self.sim_id, src=e["src"], dst=e["dst"], relation=e["relation"], fact=e["fact"],
                                weight=e["weight"], attributes=e["attributes"], round=e["round"]))
        await bus.publish(self.sim_id, "graph.delta", {"nodes": [_public_node(n) for n in nodes], "edges": [_public_edge(e) for e in edges],
                                                       "round": self.round, "note": note})
        return len(nodes) + len(edges)


def _public_node(n: dict) -> dict:
    return {"id": n["key"], "kind": n["kind"], "type": n["type"], "label": n["label"], "summary": n["summary"][:400],
            "attrs": n.get("attributes") or {}, "round": n["round"]}


def _public_edge(e: dict) -> dict:
    return {"source": e["src"], "target": e["dst"], "relation": e["relation"], "fact": e["fact"][:300], "weight": e["weight"],
            "round": e["round"]}


async def snapshot(sim_id: str, max_round: int | None = None) -> dict:
    async with session_scope() as s:
        qn = select(GraphNode).where(GraphNode.simulation_id == sim_id)
        qe = select(GraphEdge).where(GraphEdge.simulation_id == sim_id)
        if max_round is not None:
            qn = qn.where(GraphNode.round <= max_round)
            qe = qe.where(GraphEdge.round <= max_round)
        nodes = (await s.execute(qn.order_by(GraphNode.id))).scalars().all()
        edges = (await s.execute(qe.order_by(GraphEdge.id))).scalars().all()
    return {"nodes": [{"id": n.key, "kind": n.kind, "type": n.type, "label": n.label, "summary": n.summary[:400],
                       "attrs": n.attributes, "round": n.round} for n in nodes],
            "edges": [{"source": e.src, "target": e.dst, "relation": e.relation, "fact": e.fact[:300], "weight": e.weight,
                       "round": e.round} for e in edges]}


async def search(sim_id: str, query: str, limit: int = 12) -> dict:
    terms = [t for t in re.findall(r"[\w؀-ۿ]{3,}", query.lower())][:8]
    if not terms:
        return {"nodes": [], "facts": []}
    async with session_scope() as s:
        cond = or_(*[GraphNode.label.ilike(f"%{t}%") for t in terms], *[GraphNode.summary.ilike(f"%{t}%") for t in terms])
        nodes = (await s.execute(select(GraphNode).where(and_(GraphNode.simulation_id == sim_id, cond)).limit(200))).scalars().all()
        econd = or_(*[GraphEdge.fact.ilike(f"%{t}%") for t in terms], *[GraphEdge.relation.ilike(f"%{t}%") for t in terms])
        edges = (await s.execute(select(GraphEdge).where(and_(GraphEdge.simulation_id == sim_id, econd)).limit(300))).scalars().all()

    def score(text: str) -> int:
        tl = (text or "").lower()
        return sum(tl.count(t) for t in terms)

    nodes = sorted(nodes, key=lambda n: -(score(n.label) * 3 + score(n.summary)))[:limit]
    facts = sorted([e for e in edges if e.fact], key=lambda e: -score(e.fact))[:limit]
    return {"nodes": [{"key": n.key, "kind": n.kind, "type": n.type, "label": n.label, "summary": n.summary[:300]} for n in nodes],
            "facts": [{"src": e.src, "dst": e.dst, "relation": e.relation, "fact": e.fact, "round": e.round} for e in facts]}
