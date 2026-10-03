"""Knowledge graph persistence + live streaming of graph deltas."""
from __future__ import annotations

import re

import numpy as np
from sqlalchemy import or_, select

from app.db.base import utcnow
from app.db.session import session_scope
from app.models import GraphEdge, GraphNode, Simulation
from app.services.datapool.retrieval import embed
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
        self.closures: list[tuple] = []

    async def load_existing(self):
        async with session_scope() as s:
            self.known = {k for (k,) in (await s.execute(select(GraphNode.key).where(GraphNode.simulation_id == self.sim_id))).all()}
            self.edge_keys = {(a, b, r) for a, b, r in (await s.execute(select(GraphEdge.src, GraphEdge.dst, GraphEdge.relation)
                                                                       .where(GraphEdge.simulation_id == self.sim_id, GraphEdge.valid_until_round.is_(None)))).all()}

    def node(self, key: str, kind: str, label: str, type_: str = "", summary: str = "", **attrs) -> str:
        if key not in self.known:
            self.known.add(key)
            self.nodes.append({"key": key, "kind": kind, "type": type_ or kind, "label": label[:300], "summary": summary[:2000],
                               "attributes": attrs, "round": self.round})
        return key

    def edge(self, src: str, dst: str, relation: str, fact: str = "", weight: float = 1.0, **attrs) -> None:
        if src == dst and relation not in ("self",):
            return
        if relation in ("supports", "opposes"):
            opposite = "opposes" if relation == "supports" else "supports"
            self.closures.append((src, dst, opposite))
            self.edge_keys.discard((src, dst, opposite))
            self.edges = [e for e in self.edges if (e["src"], e["dst"], e["relation"]) != (src, dst, opposite)]
        elif relation == "contradicts":
            self.closures.append((None, dst, None))
            self.edge_keys = {k for k in self.edge_keys if k[1] != dst or k[2] not in ("asserts", "supports", "opposes")}
        k = (src, dst, relation)
        if k in self.edge_keys:
            return
        self.edge_keys.add(k)
        self.edges.append({"src": src, "dst": dst, "relation": relation, "fact": fact[:1000], "weight": weight,
                           "attributes": attrs, "round": self.round})

    async def flush(self, note: str | None = None) -> int:
        if not self.nodes and not self.edges and not self.closures:
            return 0
        nodes, edges = self.nodes, [e for e in self.edges if e["src"] in self.known and e["dst"] in self.known]
        self.nodes, self.edges = [], []
        updated = []
        now = utcnow()
        async with session_scope() as s:
            for src, dst, rel in self.closures:
                q = select(GraphEdge).where(GraphEdge.simulation_id == self.sim_id, GraphEdge.dst == dst,
                                           GraphEdge.valid_until_round.is_(None))
                q = q.where(GraphEdge.src == src, GraphEdge.relation == rel) if src else q.where(GraphEdge.relation.in_(["asserts", "supports", "opposes"]))
                for old in (await s.execute(q)).scalars():
                    old.valid_until_round, old.valid_until_at = self.round, now
                    updated.append(edge_public(old))
            self.closures = []
            for n in nodes:
                s.add(GraphNode(simulation_id=self.sim_id, key=n["key"], kind=n["kind"], type=n["type"], label=n["label"],
                                summary=n["summary"], attributes=n["attributes"], round=n["round"],
                                vector=embed(n["label"] + " " + n["summary"]).tolist()))
            saved_edges = []
            for e in edges:
                row = GraphEdge(simulation_id=self.sim_id, src=e["src"], dst=e["dst"], relation=e["relation"], fact=e["fact"],
                                weight=e["weight"], attributes=e["attributes"], round=e["round"],
                                valid_from_round=e["round"], valid_from_at=now)
                s.add(row)
                saved_edges.append(row)
            await s.flush()
            public_edges = [edge_public(e) for e in saved_edges]
        await bus.publish(self.sim_id, "graph.delta", {"nodes": [_public_node(n) for n in nodes], "edges": public_edges, "updated_edges": updated,
                                                       "round": self.round, "note": note})
        return len(nodes) + len(edges)


def _public_node(n: dict) -> dict:
    return {"id": n["key"], "kind": n["kind"], "type": n["type"], "label": n["label"], "summary": n["summary"][:400],
            "attrs": n.get("attributes") or {}, "round": n["round"]}


def _public_edge(e: dict) -> dict:
    return {"source": e["src"], "target": e["dst"], "relation": e["relation"], "fact": e["fact"][:300], "weight": e["weight"],
            "round": e["round"]}


def edge_public(e: GraphEdge) -> dict:
    return {"id": e.id, "source": e.src, "target": e.dst, "relation": e.relation, "fact": e.fact[:1000],
            "weight": e.weight, "round": e.round, "valid_from_round": e.valid_from_round,
            "valid_until_round": e.valid_until_round, "valid_from_at": e.valid_from_at.isoformat(),
            "valid_until_at": e.valid_until_at.isoformat() if e.valid_until_at else None,
            "source_post_ids": (e.attributes or {}).get("source_post_ids", [])}


async def snapshot(sim_id: str, max_round: int | None = None, history: bool = False) -> dict:
    async with session_scope() as s:
        qn = select(GraphNode).where(GraphNode.simulation_id == sim_id)
        qe = select(GraphEdge).where(GraphEdge.simulation_id == sim_id)
        if max_round is not None:
            qn = qn.where(GraphNode.round <= max_round)
            qe = qe.where(GraphEdge.round <= max_round)
        if not history:
            qe = qe.where(GraphEdge.valid_until_round.is_(None)) if max_round is None else qe.where(
                or_(GraphEdge.valid_until_round.is_(None), GraphEdge.valid_until_round > max_round))
        nodes = (await s.execute(qn.order_by(GraphNode.id))).scalars().all()
        edges = (await s.execute(qe.order_by(GraphEdge.id))).scalars().all()
    return {"nodes": [{"id": n.key, "kind": n.kind, "type": n.type, "label": n.label, "summary": n.summary[:400],
                       "attrs": n.attributes, "round": n.round} for n in nodes],
            "edges": [edge_public(e) for e in edges]}


async def search(sim_id: str, query: str, limit: int = 12, *, history: bool = False, hops: int = 0,
                 org_id: str | None = None) -> dict:
    """Hybrid lexical/vector retrieval, followed by bounded relation expansion. Local vectors cost no API calls."""
    terms = re.findall(r"[\w؀-ۿ]{2,}", query.lower())[:16]
    qv = embed(query)
    limit = max(1, min(40, limit))
    async with session_scope() as s:
        # Workers pass a validated simulation; public callers also pass their workspace id.
        if org_id and not (await s.execute(select(Simulation.id).where(Simulation.id == sim_id, Simulation.org_id == org_id))).scalar():
            return {"nodes": [], "facts": [], "source_node_ids": [], "source_edge_ids": []}
        base = select(GraphNode).where(GraphNode.simulation_id == sim_id)
        if s.bind.dialect.name == "postgresql":
            vec_nodes = (await s.execute(base.where(GraphNode.vector.is_not(None)).order_by(GraphNode.vector.cosine_distance(qv.tolist())).limit(200))).scalars().all()
            cond = or_(*[GraphNode.label.ilike(f"%{t}%") for t in terms], *[GraphNode.summary.ilike(f"%{t}%") for t in terms]) if terms else GraphNode.id < 0
            lexical = (await s.execute(base.where(cond).order_by(GraphNode.id.desc()).limit(400))).scalars().all()
            candidates = list({n.key: n for n in [*vec_nodes, *lexical]}.values())
        else:
            candidates = (await s.execute(base.order_by(GraphNode.id.desc()).limit(5000))).scalars().all()
        eq = select(GraphEdge).where(GraphEdge.simulation_id == sim_id)
        if not history:
            eq = eq.where(GraphEdge.valid_until_round.is_(None))
        edges = (await s.execute(eq.order_by(GraphEdge.id.desc()).limit(10000))).scalars().all()

        def score(text, vector=None):
            keyword = sum(text.lower().count(t) for t in terms) / max(1, len(terms))
            v = np.asarray(vector, dtype=np.float32) if vector is not None else embed(text)
            return .55 * min(1.0, keyword) + .45 * max(0.0, float(v @ qv))

        ranked = sorted(((score(n.label + " " + n.summary, n.vector), n) for n in candidates), key=lambda x: (-x[0], x[1].key))
        picked = {n.key: n for sc, n in ranked[:limit] if sc > .05}
        ranked_edges = sorted(((score(e.fact + " " + e.relation), e) for e in edges), key=lambda x: (-x[0], x[1].id))
        facts = {e.id: e for sc, e in ranked_edges[:limit] if sc > .05}
        frontier = set(picked) | {k for e in facts.values() for k in (e.src, e.dst)}
        for _ in range(max(0, min(2, hops))):
            related = [e for e in edges if e.src in frontier or e.dst in frontier][:80]
            facts.update({e.id: e for e in related})
            frontier |= {k for e in related for k in (e.src, e.dst)}
        missing = frontier - set(picked)
        if missing:
            extra = (await s.execute(base.where(GraphNode.key.in_(sorted(missing)[:160])))).scalars().all()
            picked.update({n.key: n for n in extra})
    return {"nodes": [{"key": n.key, "kind": n.kind, "type": n.type, "label": n.label, "summary": n.summary[:600],
                       "round": n.round, "created_at": n.created_at.isoformat()} for n in picked.values()],
            "facts": [edge_public(e) for e in facts.values()], "source_node_ids": list(picked),
            "source_edge_ids": list(facts), "method": "hybrid/local-hash-v1", "history": history}
