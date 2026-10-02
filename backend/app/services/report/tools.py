"""ReportAgent toolset. Every tool reads the finished simulation; interview_agents talks to agents."""
from __future__ import annotations

import json

from sqlalchemy import select

from app.db.session import session_scope
from app.models import Post, SimAgent, Simulation
from app.services import knowledge
from app.services.interaction import ask
from app.services.llm import BaseLLM, Usage
from app.services.simulation import agent_detail, explore

TOOL_SPECS = {
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

    async def call(self, name: str, inp: dict) -> str:
        fn = getattr(self, f"t_{name}", None)
        if fn is None:
            return f"Unknown tool '{name}'. Available: {', '.join(TOOL_SPECS)}"
        try:
            return _cut(await fn(inp if isinstance(inp, dict) else {}))
        except Exception as exc:
            return f"Tool error: {exc.__class__.__name__}: {str(exc)[:200]}"

    async def t_graph_search(self, inp):
        return await knowledge.search(self.sim.id, str(inp.get("query") or self.sim.requirement), limit=10)

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
                "headlines": [n["title"] for n in s.get("news", [])[:6]], "trending": [t["title"] for t in s.get("trending", [])[:6]],
                "events": s.get("events", [])[:3]}
