"""Step 2 · Environment setup.

* Voice agents: stratified sample of the grounded population (LLM-driven).
* Stakeholder agents: graph entities that would plausibly post (brands, media, public figures).
* Crowd: N population agents acting through a statistical policy (sampled at run time).
* Simulation config: time model on the regions' local clocks, recommender weights, scheduled events,
  live social-listening seed posts. Every field can be edited by the user before starting."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import delete, or_, select

from app.db.session import session_scope
from app.models import GraphEdge, GraphNode, Organization, SimAgent, Simulation, SocialConnection
from app.services.creator import audience_weights, weighted_sample
from app.services.datapool import listen
from app.services.events import bus
from app.services.knowledge import GraphWriter, slug
from app.services.llm import BaseLLM, LLMAuthError, Usage
from app.services.population import get_population, stratified_sample
from app.services.population.regions import PLATFORMS, REGIONS, region
from app.services.quotas import estimate_credits

from . import dry
from .prompts import CONFIG_SYSTEM, STAKEHOLDER_SYSTEM

FEED_PLATFORMS = {"tiktok", "instagram", "x", "snapchat", "facebook", "youtube", "linkedin"}


def defaults(sim: Simulation) -> dict:
    o = sim.config.get("overrides", {}) if sim.config else {}
    hours = int(o.get("hours", 24))
    mpr = int(o.get("minutes_per_round", 60))
    return {"voice": int(o.get("voice", 80)), "crowd": int(o.get("crowd", 3000)), "stakeholders": int(o.get("stakeholders", 5)),
            "hours": hours, "minutes_per_round": mpr, "platforms": o.get("platforms") or ["feed", "forum"],
            "listening": bool(o.get("listening", True)), "seed": int(o.get("seed") or 0)}


def agent_config(p: dict, pop, i: int) -> dict:
    ex, sc = float(pop.ocean[i, 2]), float(pop.screen[i])
    act = 0.12 + 0.55 * ex * sc + (0.12 if p["stance"] == "enthusiast" else 0)
    if p["stance"] == "disengaged":
        act *= 0.5
    used = {pl for k, pl in enumerate(PLATFORMS) if int(pop.platforms[i]) & (1 << k)}
    feed_w = 1.0 if used & FEED_PLATFORMS else 0.3
    forum_w = 1.0 if "reddit" in used else 0.25
    reg = region(p["region"])
    return {"activity": round(min(0.85, act), 3), "platform_weights": {"feed": feed_w, "forum": forum_w},
            "tz_offset": reg["tz_offset"], "stance": p["stance"],
            "sentiment_bias": {"enthusiast": 0.6, "neutral": 0.0, "skeptic": -0.3, "contrarian": -0.6, "disengaged": -0.1}[p["stance"]]}


async def prepare(sim_id: str, llm: BaseLLM, usage: Usage, progress) -> dict:
    async with session_scope() as s:
        sim = await s.get(Simulation, sim_id)
        d = defaults(sim)
        audience = dict(sim.audience or {})
        card = dict(sim.card or {})
        has_b = bool((sim.content or {}).get("card_b"))
        requirement = sim.requirement
        ontology = dict(sim.ontology or {})
        context = (sim.config or {}).get("context", {})
        publish_at = sim.publish_at or datetime.now(UTC)
        org_id = sim.org_id
        org = (await s.execute(select(Organization).where(Organization.id == org_id))).scalar_one()
        creator_memory = (org.settings or {}).get("creator_memory", {}).get("summary", "")
        creator_memory += "\n" + (org.settings or {}).get("creator_memory", {}).get("real_summary", "")
        from app.services.source_weights import learned_weights
        topics = card.get("topics") or {}
        learned = await learned_weights(s, max(topics, key=topics.get) if topics else None)
        for snapshot in context.values():
            snapshot["source_weights"] = {key: value["weight"] for key, value in learned["sources"].items()}
            tone = snapshot.get("tone")
            if tone:
                source = tone.get("tone_source", "gdelt")
                snapshot["source_weights"][source] = snapshot["source_weights"].get(source, 1) * tone.get("source_weight", 1)
        if audience.get("use_creator_audience"):
            profile = (org.settings or {}).get("creator_audience", {})
            split = profile.get("split")
            if profile.get("connection_id"):
                connection = (await s.execute(select(SocialConnection).where(SocialConnection.id == profile["connection_id"],
                    SocialConnection.org_id == org_id))).scalar_one_or_none()
                if connection and connection.audience:
                    split = {k: connection.audience.get(k, {}) for k in ("countries", "ages", "genders")}
            if not split or not any(split.values()):
                raise ValueError("Set up My audience or enter a follower breakdown first.")
            audience["follower_split"] = split
            sim.audience = audience
        seed = d["seed"] or (int(hashlib.sha256(sim_id.encode()).hexdigest()[:8], 16) % (2**31))
        sim.seed = seed
    pop = await get_population()
    mask = pop.mask(audience)
    n_aud = int(mask.sum())
    if n_aud < 100:
        raise ValueError(f"The audience filter matches only {n_aud} agents. Widen it.")
    rng = np.random.default_rng(seed)
    await progress(f"{n_aud:,} agents match the audience", 0.1)

    twin = None
    if audience.get("follower_split"):
        _, twin = audience_weights(pop, np.flatnonzero(mask), audience["follower_split"])
        voice_idx, _ = weighted_sample(pop, mask, d["voice"], rng, audience["follower_split"])
    else:
        voice_idx = stratified_sample(pop, mask, d["voice"], rng)
    from datetime import timedelta

    from app.db.base import utcnow
    from app.models import AgentCreatorAffinity
    from app.services.agent_memory import affinity_snapshot, creator_subject
    from app.services.interaction.selection import returning_panel
    from app.services.quotas import plan
    fresh_audience = bool((sim.config or {}).get("overrides", {}).get("fresh_audience"))
    async with session_scope() as s:
        returning_refs = (await s.execute(select(AgentCreatorAffinity.population_ref).where(AgentCreatorAffinity.org_id == org_id,
            AgentCreatorAffinity.subject == creator_subject(sim), AgentCreatorAffinity.familiarity > .1,
            AgentCreatorAffinity.last_seen_at >= utcnow() - timedelta(days=plan(org).get("memory_retention_days", 90))))).scalars().all()
    returning_ids = [int(ref[2:]) for ref in returning_refs if ref.startswith("p:") and ref[2:].isdigit()]
    requested = (sim.config or {}).get("overrides", {}).get("returning_share")
    share = 0 if fresh_audience else float(requested if requested is not None else .6 if returning_ids else 0)
    voice_idx, panel = returning_panel(pop, mask, voice_idx, returning_ids, share, rng)
    if fresh_audience:
        creator_memory = ""
    personas = [pop.persona(int(i)) for i in voice_idx]
    from app.services.datapool.retrieval import prepare_retrieval
    retrieved, retrieval_usage = await prepare_retrieval(org_id, personas, card, context, llm, usage)
    regions_in = sorted({p["region"] for p in personas})
    await progress(f"Sampled {len(personas)} voice agents across {len({(p['region'], p['age_band'], p['stance']) for p in personas})} strata", 0.25)

    # stakeholders from the knowledge graph
    async with session_scope() as s:
        ents = [{"key": n.key, "label": n.label, "type": n.type, "summary": n.summary} for n in (await s.execute(
            select(GraphNode).where(GraphNode.simulation_id == sim_id, GraphNode.kind == "entity").limit(80))).scalars()]
    from app.services.knowledge.personas import enrich_stakeholder, neighbourhoods
    neighbours = await neighbourhoods(sim_id, org_id, [e["key"] for e in ents])
    stakes = []
    if d["stakeholders"] > 0 and ents:
        if llm.is_dry:
            stakes = dry.stakeholders(ents, regions_in, d["stakeholders"])
        else:
            try:
                out = await llm.complete_json(system=STAKEHOLDER_SYSTEM, role="persona", max_tokens=2000, usage=usage, user=json.dumps({
                    "question": requirement, "content": card.get("summary"), "regions": regions_in, "max": d["stakeholders"],
                    "entities": [{"name": e["label"], "type": e["type"], "summary": e["summary"][:400], "neighbourhood": neighbours.get(e["key"], {})} for e in ents[:40]]}, ensure_ascii=False))
                stakes = [x for x in out.get("stakeholders", []) if isinstance(x, dict) and x.get("name")][: d["stakeholders"]]
            except LLMAuthError:
                raise
            except Exception:
                stakes = dry.stakeholders(ents, regions_in, d["stakeholders"])
    entity_by_name = {e["label"].casefold(): e for e in ents}
    grounded = []
    for st in stakes:
        entity = entity_by_name.get(str(st.get("entity") or st.get("name") or "").casefold())
        if entity:
            grounded.append(enrich_stakeholder(st, entity, neighbours.get(entity["key"], {})))
    stakes = grounded
    from app.services.agent_memory import attach_snapshot
    memory_snapshot = await attach_snapshot(org_id, sim_id, card,
        [(f"p:{int(i)}", p) for i, p in zip(voice_idx, personas, strict=True)] +
        [(f"s:{''.join(ch for ch in str(st.get('handle') or st['name']).lower() if ch.isalnum() or ch == '_')[:20] or f'acct{k}'}", st)
         for k, st in enumerate(stakes)], fresh=fresh_audience)
    memory_snapshot.update(panel)
    memory_snapshot["affinity"] = await affinity_snapshot(org_id, creator_subject(sim), fresh_audience, card)
    await progress(f"{len(stakes)} stakeholder accounts from the knowledge graph", 0.45)

    # model-generated configuration
    if llm.is_dry:
        gen = dry.config(d["hours"])
    else:
        try:
            gen = await llm.complete_json(system=CONFIG_SYSTEM, role="config", max_tokens=1500, usage=usage, temperature=0.4,
                                          user=json.dumps({"question": requirement, "content": {"title": card.get("title"), "summary": card.get("summary"),
                                                                                                 "topics": card.get("topic_labels")},
                                                           "hours": d["hours"], "regions": regions_in,
                                                           "live_context": {c: v.get("brief") for c, v in context.items()}}, ensure_ascii=False))
        except LLMAuthError:
            raise
        except Exception:
            gen = dry.config(d["hours"])
    base = dry.config(d["hours"])

    def clamp(v, lo, hi, dflt):
        try:
            return float(min(hi, max(lo, float(v))))
        except (TypeError, ValueError):
            return dflt

    plat_cfg = {}
    for pl in ("feed", "forum"):
        g = gen.get(pl) or {}
        b = base[pl]
        plat_cfg[pl] = {"enabled": pl in d["platforms"], "recency_weight": clamp(g.get("recency_weight"), 0.1, 0.6, b["recency_weight"]),
                        "popularity_weight": clamp(g.get("popularity_weight"), 0.1, 0.6, b["popularity_weight"]),
                        "relevance_weight": clamp(g.get("relevance_weight"), 0.1, 0.5, b["relevance_weight"]),
                        "echo_chamber": clamp(g.get("echo_chamber"), 0.0, 0.9, b["echo_chamber"]), "feed_size": 6}
    rounds = max(1, int(d["hours"] * 60 / d["minutes_per_round"]))
    sched = []
    for e in gen.get("scheduled_events") or []:
        try:
            hr = int(e.get("hour", 0))
            if 0 <= hr < d["hours"] and e.get("text"):
                sched.append({"round": int(hr * 60 / d["minutes_per_round"]), "text": str(e["text"])[:300], "source": "model"})
        except (TypeError, ValueError, AttributeError):
            continue

    # live social listening
    external = []
    if d["listening"]:
        terms = [*(card.get("keywords") or [])[:2], *(card.get("entities") or [])[:1]] or [card.get("title", "")]
        try:
            external = await listen(terms, regions_in, org_id)
        except Exception:
            external = []
    await progress(f"Social listening found {len(external)} live posts on the topic", 0.65)

    # persist agents
    async with session_scope() as s:
        await s.execute(delete(SimAgent).where(SimAgent.simulation_id == sim_id))
        acts = []
        for i, p, evidence in zip(voice_idx, personas, retrieved):
            cfg = agent_config(p, pop, int(i))
            cfg["personal_signals"] = evidence
            p["what_you_remember"] = memory_snapshot["snapshots"].get(f"p:{int(i)}", [])
            acts.append(cfg["activity"])
            s.add(SimAgent(simulation_id=sim_id, ref=f"p:{int(i)}", kind="voice", name=p["name"], handle=p["handle"], region=p["region"],
                           persona=p, config=cfg, followers=p["followers"]))
        for k, st in enumerate(stakes):
            reg = st.get("region") if st.get("region") in [r["code"] for r in REGIONS] else (regions_in[0] if regions_in else "AE")
            handle = "".join(ch for ch in str(st.get("handle") or st["name"]).lower() if ch.isalnum() or ch == "_")[:20] or f"acct{k}"
            persona = {"name": st["name"], "handle": handle, "role": st.get("role", "organisation"), "stance": st.get("stance", "neutral"),
                       "description": st.get("persona", ""), "entity": st.get("entity"), "region": reg,
                       **{key: st.get(key) for key in ("voice", "interests", "likely_stance", "posting_style", "graph_context")}}
            cfg = {"activity": clamp(st.get("activity"), 0.05, 0.9, 0.4), "platform_weights": {"feed": 1.0, "forum": 0.4},
                   "tz_offset": region(reg)["tz_offset"], "stance": persona["stance"], "sentiment_bias": 0.0}
            persona["what_you_remember"] = memory_snapshot["snapshots"].get(f"s:{handle}", [])
            acts.append(cfg["activity"])
            s.add(SimAgent(simulation_id=sim_id, ref=f"s:{handle}", kind="stakeholder", name=st["name"], handle=handle, region=reg,
                           persona=persona, config=cfg, followers=int(5000 + 20000 * cfg["activity"])))
        mean_curve = float(np.mean([np.mean(region(c)["curve"]) for c in regions_in])) if regions_in else 0.6
        config = {
            "time": {"start": publish_at.isoformat(), "hours": d["hours"], "minutes_per_round": d["minutes_per_round"], "rounds": rounds,
                     "mean_activation": round(float(np.mean(acts or [0.3])) * mean_curve, 3)},
            "agents": {"voice": len(personas), "stakeholders": len(stakes), "crowd": int(min(d["crowd"], n_aud))},
            "platforms": plat_cfg,
            "events": {"hot_topics": [str(x) for x in (gen.get("hot_topics") or [])][:8], "narrative": str(gen.get("narrative") or ""),
                       "scheduled": sched},
            "analysis_focus": str(gen.get("analysis_focus") or ontology.get("analysis_focus") or ""),
            "external_seed": external[:12], "ab": has_b, "regions": regions_in, "audience_size": n_aud,
            "behaviour": {"max_actions": 3, "memory": 6, "crowd_exposures": 4},
            "context": context, "overrides": (sim.config or {}).get("overrides", {}),
            "audience_twin": twin, "creator_memory": creator_memory, "accuracy_live_model": not llm.is_dry,
            "retrieval_usage": retrieval_usage,
            "agent_memory": memory_snapshot,
        }
        for k in ("autopilot", "watch_id", "rerun_of"):        # lifecycle markers survive regeneration
            if k in (sim.config or {}):
                config[k] = sim.config[k]
        config["credits"] = estimate_credits(config)
        sim = await s.get(Simulation, sim_id)
        sim.config = config
        sim.credits_estimate = config["credits"]["total"]
    await progress("Placing agents in the graph", 0.85)
    await graph_agents(sim_id)
    await progress("Environment ready", 1.0)
    return config


async def graph_agents(sim_id: str, batch: int = 12) -> None:
    """Agents join the knowledge graph in waves so the client watches the population assemble.
    Written at round -1 (setup) so they survive re-runs; replaced when the environment is regenerated."""
    async with session_scope() as s:
        await s.execute(delete(GraphEdge).where(GraphEdge.simulation_id == sim_id, or_(GraphEdge.src.like("agent:%"), GraphEdge.dst.like("agent:%"))))
        await s.execute(delete(GraphNode).where(GraphNode.simulation_id == sim_id, GraphNode.key.like("agent:%")))
        rows = (await s.execute(select(SimAgent).where(SimAgent.simulation_id == sim_id).order_by(SimAgent.kind.desc(), SimAgent.id))).scalars().all()
    await bus.publish(sim_id, "graph.prune", {"prefix": "agent:"})
    w = GraphWriter(sim_id, -1)
    await w.load_existing()
    for k, a in enumerate(rows):
        p = a.persona or {}
        w.node(f"agent:{a.ref}", "agent", a.name, a.kind, p.get("description") or "", region=a.region, stance=p.get("stance"),
               handle=a.handle, followers=a.followers, age=p.get("age"), city=p.get("city"))
        w.edge(f"agent:{a.ref}", f"region:{a.region}", "lives_in", "")
        if a.kind == "stakeholder" and p.get("entity"):
            w.edge(f"agent:{a.ref}", f"ent:{slug(p['entity'])}", "represents", f"{a.name} speaks for {p['entity']}")
        if (k + 1) % batch == 0 or k == len(rows) - 1:
            await w.flush(f"{k + 1} agents placed")
            await asyncio.sleep(0.12)
