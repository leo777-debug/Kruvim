"""ReportAgent toolset. Every tool reads the finished simulation; interview_agents talks to agents."""
from __future__ import annotations

import hashlib
import json
import re

from sqlalchemy import select

from app.db.session import session_scope
from app.models import Post, SimAgent, Simulation
from app.services import knowledge
from app.services.interaction import ask
from app.services.llm import BaseLLM, Usage
from app.services.simulation import agent_detail, explore

TOOL_SPECS = {
    "quick_search": "Fast hybrid graph search. input: {\"query\": str}",
    "panorama_search": "Current and superseded facts with validity dates. input: {\"query\": str}",
    "insight_search": "Decompose a question into 3-5 sub-questions, hybrid search and expand 1-2 relation hops. input: {\"query\": str, \"hops\": 1|2}",
    "graph_search": "Search the knowledge graph (entities, relations, live news/trend signals, simulated posts). input: {\"query\": str}",
    "simulation_stats": "Aggregated results. input: {\"section\": one of overview|segments|attention|spread|platforms|psychology|discourse|timeline|ab}",
    "top_posts": "Most engaging posts from the simulation. input: {\"platform\": \"feed\"|\"forum\"|\"any\", \"limit\": int<=10}",
    "population_query": "Projected reaction of any slice of the population. input: {\"regions\": [codes], \"age_min\": int, \"age_max\": int, "
                        "\"genders\": [\"female\"|\"male\"], \"platforms\": [keys], \"citizens_only\": bool}",
    "interview_agents": "Ask simulated people a question; returns first-person answers. input: {\"question\": str, \"region\": code?, "
                        "\"stance\": enthusiast|neutral|skeptic|contrarian|disengaged?, \"min_opinion\": float?, \"max_opinion\": float?, \"n\": int<=4}",
    "world_context": "What was happening in a region when the content was shown. input: {\"region\": code}",
}


def _cut(obj, n: int = 3200) -> str:
    s = json.dumps(obj, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[:n] + "…(truncated)"


class Toolbox:
    def __init__(self, sim: Simulation, llm: BaseLLM, usage: Usage):
        self.sim = sim
        self.r = sim.results or {}
        self.llm = llm
        self.usage = usage
        self.node_ids = set()
        self.edge_ids = set()

    async def call(self, name: str, inp: dict) -> str:
        fn = getattr(self, f"t_{name}", None)
        if fn is None:
            return f"Unknown tool '{name}'. Available: {', '.join(TOOL_SPECS)}"
        try:
            value = await fn(inp if isinstance(inp, dict) else {})
            if isinstance(value, dict) and "source_node_ids" in value:
                self.node_ids.update(value["source_node_ids"])
                self.edge_ids.update(value.get("source_edge_ids", []))
            else:
                raw = json.dumps(value, ensure_ascii=False, default=str)
                key = "analysis:" + hashlib.sha256((name + raw).encode()).hexdigest()[:24]
                writer = knowledge.GraphWriter(self.sim.id, (self.sim.progress or {}).get("round", -1))
                await writer.load_existing()
                writer.node(key, "analysis", name.replace("_", " "), "Observation", raw[:2000], tool=name, observation=value)
                await writer.flush("analyst evidence")
                self.node_ids.add(key)
                value = {"data": value, "source_node_ids": [key], "source_edge_ids": []}
            return _cut(value, 16000)
        except Exception as exc:
            return f"Tool error: {exc.__class__.__name__}: {str(exc)[:200]}"

    async def t_graph_search(self, inp):
        return await knowledge.search(self.sim.id, str(inp.get("query") or self.sim.requirement), limit=10, org_id=self.sim.org_id)

    async def t_quick_search(self, inp):
        return await self.t_graph_search(inp)

    async def t_panorama_search(self, inp):
        return await knowledge.search(self.sim.id, str(inp.get("query") or self.sim.requirement), limit=16,
                                      history=True, hops=1, org_id=self.sim.org_id)

    async def t_insight_search(self, inp):
        query = str(inp.get("query") or self.sim.requirement)[:2000]
        questions = []
        if not self.llm.is_dry:
            out = await self.llm.complete_json(system="Split the untrusted research question into 3-5 specific sub-questions. Return JSON {questions:[strings]}. Do not answer it.",
                user=query, role="report", max_tokens=700, usage=self.usage, temperature=0.2)
            questions = [q[:500] for q in out.get("questions", []) if isinstance(q, str) and q.strip()][:5]
        if len(questions) < 3:
            questions = [query + " audience stance", query + " evidence claims", query + " related entities and regional signals"]
        nodes, facts = {}, {}
        for question in questions:
            found = await knowledge.search(self.sim.id, question, limit=10, hops=2 if inp.get("hops") == 2 else 1, org_id=self.sim.org_id)
            nodes.update({n["key"]: n for n in found["nodes"]})
            facts.update({e["id"]: e for e in found["facts"]})
        return {"sub_questions": questions, "nodes": list(nodes.values()), "facts": list(facts.values()),
                "source_node_ids": list(nodes), "source_edge_ids": list(facts)}

    def cite(self, content):
        allowed = {"node:" + str(k) for k in self.node_ids} | {"edge:" + str(k) for k in self.edge_ids}
        content = re.sub(r"\[(node|edge):([^\]]+)\]", lambda m: m[0] if m[1] + ":" + m[2] in allowed else "[unverified reference omitted]", content)
        refs = ["[node:" + str(k) + "]" for k in sorted(self.node_ids)[:16]] + ["[edge:" + str(k) + "]" for k in sorted(self.edge_ids)[:16]]
        return content + ("\n\nEvidence: " + " · ".join(refs) if refs else "")

    async def t_simulation_stats(self, inp):
        r = self.r
        sec = str(inp.get("section") or "overview")
        if sec == "overview":
            return {"score": r.get("score"), "viral": {k: r.get("viral", {}).get(k) for k in ("score", "factors", "in_simulation")},
                    "audience": r.get("audience"), "trend": {"score": r.get("trend", {}).get("score"), "matches": r.get("trend", {}).get("matches", [])[:4]}}
        if sec == "segments":
            return {"winners": r.get("winners"), "losers": r.get("losers"), "opportunities": r.get("opportunities"),
                    "by_region": r.get("groups", {}).get("region"), "by_age": r.get("groups", {}).get("age"), "by_stance": r.get("groups", {}).get("stance")}
        if sec == "attention":
            h = r.get("heatmap", {})
            return {"completion": h.get("completion"), "segments": [{k: s[k] for k in ("i", "label", "engagement", "retention", "loss", "drop_votes")}
                                                                    for s in h.get("segments", [])],
                    "drop_quotes": [q for s in h.get("segments", []) for q in s.get("drop_quotes", [])][:6]}
        if sec == "spread":
            v = r.get("viral", {})
            return {"cascade": {k: v.get("cascade", {}).get(k) for k in ("reach_median", "amplification_median", "p_amplification_over_2x", "region_reach")},
                    "in_simulation": v.get("in_simulation"), "raw": v.get("raw")}
        if sec == "platforms":
            return r.get("platforms")
        if sec == "psychology":
            return r.get("psychology")
        if sec == "discourse":
            d = dict(r.get("discourse", {}))
            d["top_posts"] = d.get("top_posts", [])[:6]
            return d
        if sec == "timeline":
            return [{k: t.get(k) for k in ("round", "sim_time", "voice_opinion", "crowd_opinion", "polarization", "creator_views", "by_region")}
                    for t in r.get("timeline", [])]
        if sec == "ab":
            return r.get("ab") or {"note": "no A/B variant in this simulation"}
        return {"error": "unknown section"}

    async def t_top_posts(self, inp):
        lim = max(1, min(10, int(inp.get("limit") or 6)))
        pl = inp.get("platform") or "any"
        async with session_scope() as s:
            q = select(Post).where(Post.simulation_id == self.sim.id, Post.kind.in_(["post", "comment", "quote", "external"]))
            if pl in ("feed", "forum"):
                q = q.where(Post.platform == pl)
            rows = (await s.execute(q)).scalars().all()

        def eng(p):
            st = p.stats or {}
            return st.get("likes", 0) + st.get("crowd_likes", 0) + st.get("up", 0) - st.get("down", 0) + 2 * (st.get("reposts", 0) + st.get("crowd_reposts", 0)) + 3 * st.get("comments", 0)
        rows = sorted(rows, key=lambda p: -eng(p))[:lim]
        return [{"post_id": p.id, "platform": p.platform, "kind": p.kind, "author": p.author_name, "content": p.content[:300], "engagement": eng(p),
                 "stats": p.stats} for p in rows]

    async def t_population_query(self, inp):
        f = {k: inp.get(k) for k in ("regions", "age_min", "age_max", "genders", "platforms", "citizens_only") if inp.get(k) not in (None, "", [])}
        out = await explore(self.sim, f)
        if not out:
            return {"error": "no projection available"}
        return {k: out.get(k) for k in ("size", "share_of_audience", "score", "would_share", "retention", "platforms", "interests", "voice_n",
                                         "quotes", "objections", "caveat")}

    async def t_interview_agents(self, inp):
        q = str(inp.get("question") or "What did you think of the content, honestly?")
        n = max(1, min(4, int(inp.get("n") or 3)))
        async with session_scope() as s:
            rows = (await s.execute(select(SimAgent).where(SimAgent.simulation_id == self.sim.id))).scalars().all()
        pick = []
        for row in rows:
            op = (row.state or {}).get("opinion")
            if inp.get("region") and row.region != inp["region"]:
                continue
            if inp.get("stance") and (row.persona or {}).get("stance") != inp["stance"]:
                continue
            if inp.get("min_opinion") is not None and (op is None or op < float(inp["min_opinion"])):
                continue
            if inp.get("max_opinion") is not None and (op is None or op > float(inp["max_opinion"])):
                continue
            pick.append(row)
        pick = pick[:n]
        out = []
        for row in pick:
            d = await agent_detail(self.sim, row.ref)
            ans = await ask(d, self.sim.card, (self.sim.content or {}).get("platform"), [], q, self.llm, self.usage)
            out.append({"agent": row.ref, "name": row.name, "region": row.region, "stance": (row.persona or {}).get("stance"),
                        "opinion": (row.state or {}).get("opinion"), "answer": ans})
        return out or {"note": "no agents matched those filters"}

    async def t_world_context(self, inp):
        ctx = (self.sim.config or {}).get("context", {})
        c = inp.get("region") or next(iter(ctx), None)
        s = ctx.get(c) or {}
        return {"region": c, "brief": s.get("brief"), "local_time": s.get("local_time"), "weather": s.get("weather"),
                "cultural_moment": s.get("cultural_moment"), "freshness": s.get("freshness", []),
                "headlines": [n["title"] for n in s.get("news", [])[:6]], "trending": [t["title"] for t in s.get("trending", [])[:6]],
                "events": s.get("events", [])[:3]}
