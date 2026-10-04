"""Native simulated memory. Only coded own-experience data enters the batched writer."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import timedelta

import numpy as np
from sqlalchemy import delete, func, select, update

from app.db.base import utcnow
from app.db.session import session_scope
from app.models import Action, AgentCreatorAffinity, AgentMemory, Organization, Post, SimAgent, Simulation
from app.services.datapool.retrieval import embed
from app.services.knowledge import slug
from app.services.population.regions import INTERESTS
from app.services.quotas import plan

LABEL = "Simulated memories; these describe synthetic experiences, not real follower data."


def creator_subject(sim):
    return "creator:" + (slug((sim.content or {}).get("creator_subject") or "workspace")[:120] or "workspace")


def person_key(ref, persona=None):
    return "s:" + slug(persona["entity"])[:120] if ref.startswith("s:") and (persona or {}).get("entity") else ref


def topic_subject(sim):
    topics = {k: v for k, v in (sim.card or {}).get("topics", {}).items() if k in INTERESTS}
    return "topic:" + (max(topics, key=topics.get) if topics else "general")


def query_text(card):
    # Query vectors are transient: we store no content-card/raw-post text in memory.
    return " ".join([str(card.get("title", "")), str(card.get("summary", "")), " ".join(card.get("topic_labels") or [])])[:3000]


def segment_key(persona):
    if not persona.get("age"):
        return "stakeholder"
    age = int(persona["age"])
    band = 0 if age < 25 else 1 if age < 35 else 2 if age < 45 else 3 if age < 55 else 4
    return f"{persona.get('region')}:{band}:{int(persona.get('gender') == 'male')}"


def decayed(row, now):
    days = max(0, (now - row.decayed_at).total_seconds() / 86400)
    return {"familiarity": row.familiarity * math.exp(-days / 90), "affinity": row.affinity,
            "fatigue": row.fatigue * math.exp(-days / 7)}


def rule_memories(agent, sim, posts, actions, events):
    r, st = agent.reaction or {}, agent.state or {}
    score = float(st.get("opinion", r.get("score", 5)))
    initial = float(r.get("score", st.get("initial") or score))
    sentiment = float(np.clip((score - 5) / 5, -1, 1))
    counters = Counter(a.action for a in actions)
    importance = min(1, .25 + .15 * abs(sentiment) + .1 * float(r.get("emotion_intensity", 0)) + .2 * min(1, abs(score - initial) / 3) +
                     .15 * bool(posts) + .1 * bool(counters["FOLLOW"] or counters["MUTE"]) + .1 * bool(events))
    creator, topic = creator_subject(sim), topic_subject(sim)
    mood = "liked" if score >= 6.5 else "disliked" if score < 4 else "had mixed feelings about"
    own_ids = [p.id for p in posts if p.kind in ("post", "comment", "quote")]
    rows = []
    def add(kind, subject, text, ids=None, weight=importance):
        rows.append({"kind": kind, "subject": subject, "text": text, "importance": round(weight, 3),
                     "sentiment": round(sentiment, 3), "source_post_ids": ids or []})
    ending = "; I lost interest before the ending" if r.get("drop_segment") else "; I stayed interested through the ending"
    add("episodic", creator, f"I {mood} the simulated {topic[6:]} content from {creator[8:]}{ending}.")
    if own_ids or any(counters[a] for a in ("LIKE", "UPVOTE", "DOWNVOTE", "LIKE_COMMENT", "DISLIKE_COMMENT", "REPOST")):
        add("episodic", topic, "I joined the simulated discussion" + (" by posting or replying." if own_ids else " by voting or sharing."), own_ids[:8])
    if events:
        add("episodic", topic, "I reconsidered the simulated content while breaking events unfolded.")
    add("opinion", creator, f"I {mood} {creator[8:]}'s simulated content after this discussion.", weight=min(1, importance + .1))
    add("opinion", topic, f"I {mood} the simulated content about {topic[6:]}.")
    for action in [a for a in actions if a.action in ("FOLLOW", "MUTE")][:8]:
        target = action.target_ref or "creator"
        subject = creator if target == "creator" else "account:" + slug(target)[:120]
        add("relationship", subject, f"I {'followed' if action.action == 'FOLLOW' else 'muted'} the simulated account {subject.split(':', 1)[1]}.", weight=.9)
    return rows


async def write_run(org_id, sim_id, llm, usage, now=None):
    """One model call per 20 people; commit all writes + receipt together, once per execution."""
    now = now or utcnow()
    async with session_scope() as s:
        sim = (await s.execute(select(Simulation).where(Simulation.id == sim_id, Simulation.org_id == org_id))).scalar_one()
        execution = sim.started_at.isoformat() if sim.started_at else "completed"
        if sim.status != "completed" or (sim.config or {}).get("memory_written") == execution:
            return 0
        agents = (await s.execute(select(SimAgent).where(SimAgent.simulation_id == sim_id).order_by(SimAgent.ref))).scalars().all()
        posts = (await s.execute(select(Post).where(Post.simulation_id == sim_id, Post.kind.in_(["post", "comment", "quote"])))).scalars().all()
        actions = (await s.execute(select(Action).where(Action.simulation_id == sim_id, Action.actor_ref.in_([a.ref for a in agents])))).scalars().all()
        events = (await s.execute(select(func.count()).select_from(Post).where(Post.simulation_id == sim_id, Post.kind == "event"))).scalar()
    by_post, by_action = defaultdict(list), defaultdict(list)
    for post in posts:
        by_post[post.author_ref].append(post)
    for action in actions:
        by_action[action.actor_ref].append(action)
    records = {}
    for offset in range(0, len(agents), 20):
        batch = agents[offset:offset + 20]
        generated = {a.ref: rule_memories(a, sim, by_post[a.ref], by_action[a.ref], events) for a in batch}
        if not llm.is_dry:
            try:
                out = await llm.complete_json(system="Rewrite each supplied simulated experience as one short first-person sentence. "
                    "Never invent content, quotes or real-person information. Preserve all ref, kind, subject and provenance fields. "
                    "Return {agents: [{ref, memories: [{text}]}]} with exactly the supplied ordering per agent.",
                    user=json.dumps({"agents": [{"ref": ref, "memories": rows} for ref, rows in generated.items()]}),
                    role="report", max_tokens=4096, usage=usage, temperature=0)
                for item in out.get("agents", []):
                    base = generated.get(item.get("ref"))
                    rewritten = item.get("memories", [])
                    if not base or len(rewritten) != len(base):
                        continue
                    for row, new in zip(base, rewritten, strict=True):
                        text = str(new.get("text", "")).strip()
                        if text.startswith(("I ", "My ")) and len(text.split()) <= 45 and len(text) <= 300:
                            row["text"] = text
            except Exception:
                # Memory is supplementary; provider failures retain the same deterministic experience data.
                pass
        records.update(generated)
    async with session_scope() as s:
        org = (await s.execute(select(Organization).where(Organization.id == org_id).with_for_update())).scalar_one()
        current = (await s.execute(select(Simulation).where(Simulation.id == sim_id, Simulation.org_id == org_id).with_for_update())).scalar_one()
        if (current.config or {}).get("memory_written") == execution:
            return 0
        # A reset during preparation/extraction must not resurrect deleted memory.
        generation = (sim.config or {}).get("agent_memory", {}).get("generation", 0)
        if generation != (org.settings or {}).get("agent_memory_generation", 0):
            return 0
        refs = [person_key(a.ref, a.persona) for a in agents]
        prior = (await s.execute(select(AgentMemory).where(AgentMemory.org_id == org_id,
            AgentMemory.population_ref.in_(refs), AgentMemory.superseded_by.is_(None)))).scalars().all()
        prior_by_key = defaultdict(list)
        for old in prior:
            prior_by_key[(old.population_ref, old.kind, old.subject)].append(old)
        affinities = (await s.execute(select(AgentCreatorAffinity).where(AgentCreatorAffinity.org_id == org_id,
            AgentCreatorAffinity.population_ref.in_(refs), AgentCreatorAffinity.subject == creator_subject(sim)))).scalars().all()
        by_affinity = {a.population_ref: a for a in affinities}
        topic_vector = embed(query_text(sim.card or {}) or topic_subject(sim)).tolist()
        count = 0
        for agent in agents:
            key = person_key(agent.ref, agent.persona)
            for pos, data in enumerate(records[agent.ref]):
                identifier = hashlib.sha256(f"{org_id}:{sim_id}:{execution}:{key}:{pos}".encode()).hexdigest()[:32]
                memory = AgentMemory(id=identifier, org_id=org_id, population_ref=key, source_simulation_id=sim_id,
                    embedding=embed(data["text"] + " " + data["subject"]).tolist(), created_at=now, recall_count=0, **data)
                s.add(memory)
                await s.flush()
                if memory.kind in ("opinion", "relationship"):
                    for old in prior_by_key[(key, memory.kind, memory.subject)]:
                        old.superseded_by = identifier
                count += 1
            affinity = by_affinity.get(key)
            sentiment = float(np.clip((float((agent.state or {}).get("opinion", (agent.reaction or {}).get("score", 5))) - 5) / 5, -1, 1))
            if affinity:
                state = decayed(affinity, now)
                similarity = float(np.asarray(affinity.topic_embedding) @ np.asarray(topic_vector))
                days = max(0, (now - affinity.last_seen_at).total_seconds() / 86400)
                affinity.familiarity = state["familiarity"] + 1
                affinity.affinity = .7 * affinity.affinity + .3 * sentiment
                affinity.fatigue = min(1, state["fatigue"] + .2 * max(0, similarity) * math.exp(-days / 7))
                affinity.last_seen_at = affinity.decayed_at = now
                affinity.topic_embedding = topic_vector
            else:
                s.add(AgentCreatorAffinity(org_id=org_id, population_ref=key, subject=creator_subject(sim), familiarity=1,
                    affinity=sentiment, fatigue=0, last_seen_at=now, decayed_at=now, topic_embedding=topic_vector,
                    segment=segment_key(agent.persona)))
        current.config = {**(current.config or {}), "memory_written": execution}
        await s.flush()
        await enforce_limits(s, org, now)
    return count


async def enforce_limits(s, org, now):
    """Bound physical rows, including superseded history, rather than only active recall rows."""
    limits = plan(org)
    days, cap = limits.get("memory_retention_days", 90), limits.get("memory_cap_per_agent", 60)
    await s.execute(delete(AgentMemory).where(AgentMemory.org_id == org.id, AgentMemory.created_at < now - timedelta(days=days)))
    rows = (await s.execute(select(AgentMemory.id, AgentMemory.population_ref).where(AgentMemory.org_id == org.id)
        .order_by(AgentMemory.superseded_by.is_not(None), AgentMemory.importance.desc(), AgentMemory.created_at.desc(), AgentMemory.id))).all()
    seen, remove = Counter(), []
    for identifier, ref in rows:
        seen[ref] += 1
        if seen[ref] > cap:
            remove.append(identifier)
    for offset in range(0, len(remove), 400):
        await s.execute(delete(AgentMemory).where(AgentMemory.org_id == org.id, AgentMemory.id.in_(remove[offset:offset + 400])))


def token_cost(text):
    # Conservative native estimate; no tokenizer or remote service is required.
    return max(1, math.ceil(len(text.encode("utf-8")) / 4), math.ceil(len(text.split()) * 1.4))


def ranked_memories(rows, query_vector, now, k=6, budget=150):
    scored = []
    for row, similarity in rows:
        relevance = float(np.asarray(row.embedding) @ query_vector) if similarity is None else float(similarity)
        days = max(0, (now - row.created_at).total_seconds() / 86400)
        scored.append((relevance + math.exp(-days / 30) + row.importance, row))
    scored.sort(key=lambda x: (-x[0], x[1].id))
    selected, used = [], 0
    for score, row in scored:
        cost = token_cost(row.text)
        if used + cost <= budget:
            selected.append({"id": row.id, "text": row.text, "kind": row.kind, "subject": row.subject,
                "importance": row.importance, "sentiment": row.sentiment, "source_simulation_id": row.source_simulation_id,
                "created_at": row.created_at.isoformat(), "rank_score": round(score, 4)})
            used += cost
        if len(selected) >= k:
            break
    return selected


async def recall_many(s, org, refs, card, now=None, fresh=False, record=True):
    """Batch candidate reads, pgvector cosine on Postgres, native embeddings on SQLite."""
    now = now or utcnow()
    out = {ref: [] for ref in refs}
    if fresh or not refs:
        return out
    query_vector = embed(query_text(card))
    for offset in range(0, len(refs), 200):
        query = select(AgentMemory).where(AgentMemory.org_id == org.id,
            AgentMemory.population_ref.in_(refs[offset:offset + 200]), AgentMemory.superseded_by.is_(None),
            AgentMemory.created_at >= now - timedelta(days=plan(org).get("memory_retention_days", 90)), AgentMemory.created_at <= now)
        pg = s.bind.dialect.name == "postgresql"
        if pg:
            query = query.add_columns(1 - AgentMemory.embedding.cosine_distance(query_vector.tolist()))
        result = (await s.execute(query)).all()
        grouped = defaultdict(list)
        for row in result:
            memory = row[0]
            grouped[memory.population_ref].append((memory, row[1] if pg else None))
        for ref, candidates in grouped.items():
            out[ref] = ranked_memories(candidates, query_vector, now)
    if record:
        ids = [m["id"] for rows in out.values() for m in rows]
        for offset in range(0, len(ids), 400):
            await s.execute(update(AgentMemory).where(AgentMemory.org_id == org.id, AgentMemory.id.in_(ids[offset:offset + 400]))
                            .values(recall_count=AgentMemory.recall_count + 1, last_recalled_at=now))
    return out


def remember_block(memories):
    return "\nWhat you remember (simulated experiences):\n" + "\n".join("- " + m["text"] for m in memories) if memories else ""


async def attach_snapshot(org_id, sim_id, card, agents, fresh=False):
    now = utcnow()
    async with session_scope() as s:
        org = (await s.execute(select(Organization).where(Organization.id == org_id).with_for_update())).scalar_one()
        keys = [person_key(ref, persona) for ref, persona in agents]
        recalled = await recall_many(s, org, keys, card, now, fresh=fresh)
        snapshot = {ref: recalled.get(key, []) for (ref, _), key in zip(agents, keys, strict=True)}
        opinions = {}
        if not fresh:
            run = (await s.execute(select(Simulation).where(Simulation.id == sim_id, Simulation.org_id == org_id))).scalar_one()
            query_vector = embed(query_text(card))
            for offset in range(0, len(keys), 200):
                rows = (await s.execute(select(AgentMemory).where(AgentMemory.org_id == org_id,
                    AgentMemory.population_ref.in_(keys[offset:offset + 200]), AgentMemory.kind == "opinion",
                    AgentMemory.subject.in_([creator_subject(run), topic_subject(run)]), AgentMemory.importance >= .65,
                    AgentMemory.superseded_by.is_(None), AgentMemory.created_at <= now,
                    AgentMemory.created_at >= now - timedelta(days=plan(org).get("memory_retention_days", 90))))).scalars().all()
                grouped = defaultdict(list)
                for row in rows:
                    grouped[row.population_ref].append((row, None))
                for (ref, _), key in zip(agents, keys, strict=True):
                    if key in grouped:
                        opinions[ref] = ranked_memories(grouped[key], query_vector, now, k=2, budget=75)
            extra = sorted({m["id"] for values in opinions.values() for m in values} - {m["id"] for values in snapshot.values() for m in values})
            for offset in range(0, len(extra), 400):
                await s.execute(update(AgentMemory).where(AgentMemory.org_id == org_id, AgentMemory.id.in_(extra[offset:offset + 400]))
                    .values(recall_count=AgentMemory.recall_count + 1, last_recalled_at=now))
        return {"snapshot_at": now.isoformat(), "generation": (org.settings or {}).get("agent_memory_generation", 0),
            "fresh": fresh, "snapshots": snapshot, "opinion_snapshots": opinions,
            "recalled": len({m["id"] for values in [*snapshot.values(), *opinions.values()] for m in values}), "label": LABEL}


async def affinity_snapshot(org_id, subject, fresh=False, card=None):
    if fresh:
        return {"people": {}, "segments": {}}
    now = utcnow()
    async with session_scope() as s:
        org = await s.get(Organization, org_id)
        rows = (await s.execute(select(AgentCreatorAffinity).where(AgentCreatorAffinity.org_id == org_id,
            AgentCreatorAffinity.subject == subject, AgentCreatorAffinity.last_seen_at >= now - timedelta(days=plan(org).get("memory_retention_days", 90))))).scalars().all()
    grouped, people = defaultdict(list), {}
    for row in rows:
        state = decayed(row, now)
        if card is not None:
            state["fatigue"] *= max(0, float(np.asarray(row.topic_embedding) @ embed(query_text(card) or "topic:general")))
        if row.population_ref.startswith("p:"):
            people[row.population_ref[2:]] = state
            grouped[row.segment].append(state)
    return {"people": people, "segments": {key: {field: float(np.mean([r[field] for r in records]))
        for field in ("familiarity", "affinity", "fatigue")} for key, records in grouped.items()},
        "method": "Segment averages over remembered simulated people; extrapolated to the crowd, not real follower history."}


def adjust_reaction(reaction, state):
    """Conservative, explicit dry-run history prior; never an accuracy claim."""
    reaction = dict(reaction)
    affinity, fatigue = state.get("affinity", 0), state.get("fatigue", 0)
    reaction["score"] = float(np.clip(reaction["score"] + .35 * affinity - .45 * fatigue, 0, 10))
    reaction["would_share"] = float(np.clip(reaction.get("would_share", 0) + .04 * affinity - .04 * fatigue, 0, 1))
    reaction["novelty"] = float(np.clip(reaction.get("novelty", .5) * (1 - .3 * fatigue), 0, 1))
    reaction["rewatch_probability"] = float(np.clip(reaction.get("rewatch_probability", reaction["score"] / 10 * .35) * (1 - .3 * fatigue), 0, 1))
    return reaction




async def detail_memory(sim, ref, persona):
    key, now = person_key(ref, persona), utcnow()
    async with session_scope() as s:
        org = (await s.execute(select(Organization).where(Organization.id == sim.org_id))).scalar_one()
        rows = (await s.execute(select(AgentMemory).where(AgentMemory.org_id == sim.org_id, AgentMemory.population_ref == key,
            AgentMemory.superseded_by.is_(None), AgentMemory.created_at >= now - timedelta(days=plan(org).get("memory_retention_days", 90)))
            .order_by(AgentMemory.created_at.desc(), AgentMemory.id).limit(plan(org).get("memory_cap_per_agent", 60)))).scalars().all()
        affinity = (await s.execute(select(AgentCreatorAffinity).where(AgentCreatorAffinity.org_id == sim.org_id,
            AgentCreatorAffinity.population_ref == key, AgentCreatorAffinity.subject == creator_subject(sim)))).scalar_one_or_none()
        fresh = (sim.config or {}).get("agent_memory", {}).get("fresh", False)
        recalled = (await recall_many(s, org, [key], sim.card or {}, fresh=fresh, record=False))[key]
        return {"label": LABEL, "fresh": fresh, "recalled": recalled, "affinity": decayed(affinity, now) if affinity else None,
            "memories": [{"id": m.id, "kind": m.kind, "text": m.text, "subject": m.subject, "importance": m.importance,
                "created_at": m.created_at.isoformat(), "source_simulation_id": m.source_simulation_id} for m in rows]}


async def audience_summary(s, org, subject=None):
    now = utcnow()
    query = select(AgentCreatorAffinity).where(AgentCreatorAffinity.org_id == org.id,
        AgentCreatorAffinity.last_seen_at >= now - timedelta(days=plan(org).get("memory_retention_days", 90)))
    if subject:
        subject = "creator:" + slug(subject.removeprefix("creator:"))[:120]
        query = query.where(AgentCreatorAffinity.subject == subject)
    rows = (await s.execute(query)).scalars().all()
    states = [decayed(row, now) for row in rows]
    mean = lambda key: round(float(np.mean([x[key] for x in states])), 3) if states else 0  # noqa: E731
    return {"label": LABEL, "subject": subject, "agents": len({r.population_ref for r in rows}), "familiarity": mean("familiarity"),
        "affinity": mean("affinity"), "fatigue": mean("fatigue"), "fatigue_warning": mean("fatigue") >= .5,
        "default_returning_share": .6 if rows else 0, "subjects": sorted({r.subject for r in rows}),
        "retention_days": plan(org).get("memory_retention_days", 90), "cap_per_agent": plan(org).get("memory_cap_per_agent", 60)}
