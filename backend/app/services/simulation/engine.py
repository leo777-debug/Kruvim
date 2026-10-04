"""Step 3 · Dual-platform social simulation.

Each round is one slice of simulated time on every region's local clock. Per round:
  1. control channel (pause / resume / stop / inject God's-eye events) and scheduled events
  2. LLM agents (voice + stakeholder) wake up with probability activity × local-hour curve, read a
     recommender-ranked feed and act: POST, COMMENT, REPOST, QUOTE, LIKE, FOLLOW / UPVOTE, DOWNVOTE
  3. the crowd (thousands of population agents) acts through a vectorised policy fitted on the voice
     agents' first reactions: exposures, likes, reposts, votes and bounded-confidence opinion drift
  4. posts, actions, metrics and graph deltas are persisted and streamed to every watching client
Round 0 is first exposure: every voice agent reacts to the content in depth (score, attention per
segment, emotion, quote) - the basis for the heatmap and the population projection."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import numpy as np
from sqlalchemy import select, update

from app.core.metrics import SIM_ACTIONS
from app.db.session import session_scope
from app.models import Action, Organization, Post, SimAgent, Simulation
from app.services import jobs
from app.services.content import card_block, topic_vector
from app.services.creator import short_video_metrics, weighted_sample
from app.services.datapool.retrieval import embed
from app.services.events import bus
from app.services.knowledge import GraphWriter, slug
from app.services.llm import BaseLLM, LLMAuthError, LLMError, Usage
from app.services.population import get_population, persona_text, platform_label, topic_match
from app.services.population.regions import PLATFORMS, REGIONS, STANCES, region

from . import dry, projection
from .prompts import FEED_ACTIONS, FORUM_ACTIONS, action_system, action_user, reaction_system

log = logging.getLogger("kruvim.sim")
BASE_TARGETS = ["score", "would_share", "would_comment", "would_follow", "emotion_intensity", "novelty"]
DRY_PACE = 0.02


class Stopped(Exception):
    pass


@dataclass
class AgentRT:
    id: int
    ref: str
    kind: str
    name: str
    handle: str
    region: str
    persona: dict
    cfg: dict
    followers: int
    opinion: float = 5.0
    initial: float | None = None
    memory: list = field(default_factory=list)
    following: set = field(default_factory=set)
    muted: set = field(default_factory=set)
    comment_votes: dict = field(default_factory=dict)
    discoveries: set = field(default_factory=set)
    seen: set = field(default_factory=set)
    actions: int = 0
    trajectory: list = field(default_factory=list)
    reaction: dict | None = None


@dataclass
class PostRT:
    id: int
    platform: str
    kind: str
    author_ref: str
    author_name: str
    author_region: str
    content: str
    round: int
    stance: float | None
    parent_id: int | None = None
    root_id: int | None = None
    likes: int = 0
    reposts: int = 0
    comments: int = 0
    quotes: int = 0
    up: int = 0
    down: int = 0
    views: int = 0
    crowd_likes: int = 0
    crowd_reposts: int = 0
    dirty: bool = True

    def stats(self) -> dict:
        return {"likes": self.likes, "reposts": self.reposts, "comments": self.comments, "quotes": self.quotes, "up": self.up,
                "down": self.down, "views": self.views, "crowd_likes": self.crowd_likes, "crowd_reposts": self.crowd_reposts}

    def popularity(self) -> float:
        engagement = (self.likes + 2 * self.reposts + 3 * self.comments + 2 * self.quotes + 0.25 * self.crowd_likes
                      + 0.5 * self.crowd_reposts + self.up - 0.5 * self.down)
        # Downvotes can outweigh all positive engagement. Such posts get no
        # popularity boost; log1p on a value <= -1 would crash the whole run.
        return math.log1p(max(0, engagement)) / math.log1p(60)


def _f(v, d, lo=None, hi=None):
    try:
        x = float(v)
        if x != x:
            raise ValueError
    except (TypeError, ValueError):
        x = d
    if lo is not None:
        x = max(lo, x)
    if hi is not None:
        x = min(hi, x)
    return x


def norm_reaction(d: dict, n_seg: int, poll_n: int = 0) -> dict:
    d = d if isinstance(d, dict) else {}
    score = _f(d.get("score"), 5.0, 0, 10)
    raw = d.get("segment_engagement") if isinstance(d.get("segment_engagement"), list) else []
    seg = [_f(x, 0.85, 0.02, 0.999) for x in raw[:n_seg]]
    if len(seg) < n_seg:
        seg += [float(np.mean(seg)) if seg else 0.85] * (n_seg - len(seg))
    try:
        drop = int(d.get("drop_segment")) if d.get("drop_segment") not in (None, "", "null") else None
        drop = drop if drop and 1 <= drop <= n_seg else None
    except (TypeError, ValueError):
        drop = None
    sent = str(d.get("sentiment") or "").lower()
    if sent not in ("positive", "neutral", "negative"):
        sent = "positive" if score >= 6.5 else "negative" if score < 4 else "neutral"
    drivers = d.get("drivers") if isinstance(d.get("drivers"), list) else []
    return {"score": round(score, 1), "sentiment": sent, "primary_emotion": str(d.get("primary_emotion") or "neutral").lower()[:24],
            "emotion_intensity": _f(d.get("emotion_intensity"), 0.4, 0, 1), "would_share": _f(d.get("would_share"), 0.05, 0, 1),
            "would_comment": _f(d.get("would_comment"), 0.05, 0, 1), "would_follow": _f(d.get("would_follow"), 0.02, 0, 1),
            "novelty": _f(d.get("novelty"), 0.4, 0, 1), "segment_engagement": [round(x, 3) for x in seg], "drop_segment": drop,
            "drivers": [str(x).lower()[:30] for x in drivers][:3], "decision_mode": str(d.get("decision_mode") or "")[:20].lower(),
            "objection": str(d.get("objection") or "")[:160], "quote": str(d.get("quote") or "")[:300],
            "reason": str(d.get("reason") or "")[:300]} | ({"poll_choice": int(_f(d.get("poll_choice"), 0, 0, poll_n))} if poll_n else {})


class Engine:
    def __init__(self, sim_id: str, llm: BaseLLM, usage: Usage):
        self.sim_id = sim_id
        self.llm = llm
        self.usage = usage
        self.dry = llm.is_dry
        self.agents: dict[str, AgentRT] = {}
        self.posts: dict[int, PostRT] = {}
        self.by_platform: dict[str, list[int]] = {"feed": [], "forum": []}
        self.round = 0
        self.timeline: list[dict] = []
        self.counts = Counter()
        self.breaking: list[str] = []
        self.failures: list[str] = []
        self.speed = 1.0

    # ------------------------------------------------------------------------------------------------
    async def emit(self, type_: str, payload: dict):
        await bus.publish(self.sim_id, type_, payload)

    def sim_time(self, r: int) -> datetime:
        return self.start + timedelta(minutes=r * self.mpr)

    def local(self, code: str, r: int) -> datetime:
        return self.sim_time(r) + timedelta(hours=region(code)["tz_offset"])

    def curve(self, code: str, r: int) -> float:
        return region(code)["curve"][self.local(code, r).hour]

    # ------------------------------------------------------------------------------------------------
    async def load(self):
        async with session_scope() as s:
            sim = await s.get(Simulation, self.sim_id)
            self.cfg = dict(sim.config)
            org = await s.get(Organization, sim.org_id)
            if self.cfg.get("agent_memory", {}).get("generation", 0) != (org.settings or {}).get("agent_memory_generation", 0):
                self.cfg["agent_memory"] = {**self.cfg.get("agent_memory", {}), "fresh": True, "snapshots": {},
                    "opinion_snapshots": {}, "affinity": {"people": {}, "segments": {}}, "recalled": 0,
                    "reset_since_preparation": True}
                self.cfg["creator_memory"] = ""
            self.card = dict(sim.card)
            self.card_b = (sim.content or {}).get("card_b")
            self.b_kind = (sim.content or {}).get("b_kind") or "version"
            self.creator_followers = (sim.content or {}).get("creator_followers")
            self.seed = sim.seed or 7
            self.audience = dict(sim.audience or {})
            self.platform_key = (sim.content or {}).get("platform")
            rows = (await s.execute(select(SimAgent).where(SimAgent.simulation_id == self.sim_id))).scalars().all()
        for r in rows:
            self.agents[r.ref] = AgentRT(r.id, r.ref, r.kind, r.name, r.handle, r.region, r.persona, r.config, r.followers)
        t = self.cfg["time"]
        self.start = datetime.fromisoformat(t["start"]) if t.get("start") else datetime.now(UTC)
        if self.start.tzinfo is None:
            self.start = self.start.replace(tzinfo=UTC)
        self.mpr = int(t["minutes_per_round"])
        self.rounds = int(t["rounds"])
        self.rng = np.random.default_rng(self.seed)
        self.pop = await get_population()
        self.topic_vec = topic_vector(self.card.get("topics"))
        self.snaps = self.cfg.get("context", {})
        self.world_block = "\n".join(f"{v.get('name')} ({v.get('city')}): {v.get('brief')}" for v in self.snaps.values()) or "No live context."
        self.world_block += "\n" + "\n".join(f"{code} cultural moment: {snapshot.get('cultural_moment', '')}" for code, snapshot in self.snaps.items())
        if self.cfg.get("creator_memory"):
            self.world_block += "\nCreator audience memory (simulated observations): " + self.cfg["creator_memory"]
        self.enabled = [p for p in ("feed", "forum") if self.cfg["platforms"][p]["enabled"]] or ["feed"]
        self.writer = GraphWriter(self.sim_id, 0)
        await self.writer.load_existing()

    # ---- posts & actions ----------------------------------------------------------------------------
    async def new_post(self, s, platform, kind, author_ref, author_name, author_region, content, stance, parent=None, variant="A", url=None) -> PostRT:
        root = None
        if parent is not None:
            root = self.posts[parent].root_id or parent
        row = Post(simulation_id=self.sim_id, platform=platform, kind=kind, author_ref=author_ref, author_name=author_name, parent_id=parent,
                   root_id=root, variant=variant, content=content[:4000], round=self.round, sim_time=self.sim_time(self.round), stats={},
                   sentiment=0.0 if stance is None else (stance - 5) / 5, source_url=url)
        s.add(row)
        await s.flush()
        p = PostRT(row.id, platform, kind, author_ref, author_name, author_region, content, self.round, stance, parent, root)
        self.posts[p.id] = p
        self.by_platform[platform].append(p.id)
        if parent is not None:
            par = self.posts[parent]
            if kind == "comment":
                par.comments += 1
            elif kind == "quote":
                par.quotes += 1
            par.dirty = True
        return p

    def log_action(self, s, a: AgentRT | None, platform, action, post_id=None, target_post=None, target_ref=None, content="", meta=None,
                   actor_ref=None, actor_name=None):
        s.add(Action(simulation_id=self.sim_id, round=self.round, sim_time=self.sim_time(self.round), platform=platform,
                     actor_ref=actor_ref or a.ref, actor_name=actor_name or (a.name if a else ""), action=action, post_id=post_id,
                     target_post_id=target_post, target_ref=target_ref, content=content[:2000], meta=meta or {}))
        self.counts[(platform, action)] += 1
        SIM_ACTIONS.labels(platform, action).inc()

    def post_view(self, p: PostRT) -> dict:
        author = self.agents.get(p.author_ref)
        who = (f"{author.persona.get('age', '')} {author.persona.get('city', '')}".strip() if author and author.kind == "voice"
               else (author.persona.get("role", "account") if author else {"creator": "creator", "event": "breaking news"}.get(p.author_ref, "external")))
        return {"id": p.id, "platform": p.platform, "kind": p.kind, "author": author.handle if author else p.author_name, "who": who,
                "content": p.content, "stats": p.stats(), "stance": p.stance if p.stance is not None else 5.0}

    def recommend(self, a: AgentRT, platform: str, k: int) -> list[PostRT]:
        w = self.cfg["platforms"][platform]
        cand = self.by_platform[platform][-500:]
        scored = []
        for pid in cand:
            p = self.posts[pid]
            if p.author_ref == a.ref or pid in a.seen or p.kind == "repost" or p.author_ref in a.muted:
                continue
            rec = math.exp(-(self.round - p.round) / 5.0)
            rel = (0.5 if p.author_region == a.region else 0.0) + (1.0 if p.author_ref in a.following else 0.0) + \
                  (0.8 if p.author_ref in ("creator", "event") else 0.0)
            echo = 0.0 if p.stance is None else w["echo_chamber"] * (1 - abs(a.opinion - p.stance) / 10)
            sc = w["recency_weight"] * rec + w["popularity_weight"] * p.popularity() + w["relevance_weight"] * rel + echo
            scored.append((sc + self.rng.gumbel() * 0.15, p))
        scored.sort(key=lambda x: -x[0])
        return [p for _, p in scored[:k]]

    def search_posts(self, a: AgentRT, platform: str, query: str) -> list[dict]:
        if not query.strip():
            return []
        qv, terms = embed(query), query.lower().split()
        ranked = []
        for p in self.posts.values():
            if p.platform != platform or p.author_ref in a.muted or p.kind == "repost":
                continue
            lexical = sum(t in p.content.lower() for t in terms) / max(1, len(terms))
            score = .55 * lexical + .45 * max(0, float(embed(p.content) @ qv))
            if score > .05:
                ranked.append((score, p))
        return [self.post_view(p) for _, p in sorted(ranked, key=lambda x: (-x[0], x[1].id))[:6]]

    def search_users(self, a: AgentRT, query: str) -> list[dict]:
        if not query.strip():
            return []
        qv, terms = embed(query), query.lower().split()
        ranked = []
        for user in self.agents.values():
            if user.ref in a.muted:
                continue
            text = f"{user.name} {user.handle} {user.region} {user.persona.get('description', '')}"
            score = .55 * sum(t in text.lower() for t in terms) / max(1, len(terms)) + .45 * max(0, float(embed(text) @ qv))
            if score > .05:
                ranked.append((score, user))
        return [{"ref": u.ref, "handle": u.handle, "name": u.name, "region": u.region}
                for _, u in sorted(ranked, key=lambda x: (-x[0], x[1].ref))[:6]]

    # ---- round 0: first exposure ------------------------------------------------------------------------
    async def first_exposure(self):
        await self.emit("round.start", self.round_meta(0))
        async with session_scope() as s:
            self.creator = {}
            text = self.card.get("summary") if self.card.get("type") in ("video", "audio", "image") else ""
            body = " ".join(seg["text"] for seg in self.card.get("segments", []))[:600]
            for pl in self.enabled:
                main = text or body
                head = self.card["title"].rstrip("…")
                content = (main if main.startswith(head) else f"{self.card['title']}\n{main}").strip()
                p = await self.new_post(s, pl, "post", "creator", "Creator", (self.cfg.get("regions") or ["AE"])[0], content, None)
                self.creator[pl] = p.id
                self.writer.node(f"post:{p.id}", "post", self.card["title"][:80], f"creator · {pl}", content[:300], platform=pl)
                self.writer.edge("content:A", f"post:{p.id}", "published_as", f"Published on the {pl}")
                self.log_action(s, None, pl, "POST", post_id=p.id, content=content, actor_ref="creator", actor_name="Creator")
            for e in self.cfg.get("external_seed", []):
                pl = "forum" if e.get("platform") == "reddit" and "forum" in self.enabled else self.enabled[0]
                p = await self.new_post(s, pl, "external", f"ext:{e.get('platform')}", e.get("author") or e.get("platform"), "*",
                                        e.get("text", ""), 5.0, url=e.get("url"))
                p.likes = int(min(500, e.get("engagement") or 0))
                self.writer.node(f"post:{p.id}", "post", (e.get("text") or "")[:80], f"live · {e.get('platform')}", e.get("text", "")[:300],
                                 platform=pl, url=e.get("url"))
        # graph: agents + crowd clusters
        for a in self.agents.values():
            self.writer.node(f"agent:{a.ref}", "agent", a.name, a.kind, a.persona.get("description") or "", region=a.region,
                             stance=a.persona.get("stance"), handle=a.handle, followers=a.followers,
                             age=a.persona.get("age"), city=a.persona.get("city"))
            self.writer.edge(f"agent:{a.ref}", f"region:{a.region}", "lives_in", "")
            if a.kind == "stakeholder" and a.persona.get("entity"):
                self.writer.edge(f"agent:{a.ref}", f"ent:{slug(a.persona['entity'])}", "represents", f"{a.name} speaks for {a.persona['entity']}")
        await self.writer.flush("agents joined")

        voices = [a for a in self.agents.values() if a.kind == "voice"]
        cards = {"A": self.card} | ({"B": self.card_b} if self.card_b else {})
        plab = platform_label(self.platform_key)
        systems = {v: reaction_system(card_block(c), self.world_block, len(c["segments"]), plab, len(c.get("poll_options") or []))
                   for v, c in cards.items()}

        async def react(a: AgentRT, v: str):
            idx = int(a.ref[2:])
            c = cards[v]
            if self.dry:
                await asyncio.sleep(DRY_PACE)
                tm = float(topic_match(self.pop, np.array([idx]), topic_vector(c.get("topics")))[0])
                on_t = self.platform_key not in PLATFORMS or bool((int(self.pop.platforms[idx]) >> PLATFORMS.index(self.platform_key)) & 1)
                reaction = dry.reaction(a.persona, tm, on_t, c, self.snaps.get(a.region), np.random.default_rng([self.seed, idx, ord(v)]))
                reaction["fresh_score"] = reaction["score"]
                from app.services.agent_memory import adjust_reaction
                state = self.cfg.get("agent_memory", {}).get("affinity", {}).get("people", {}).get(str(idx), {})
                reaction = adjust_reaction(reaction, state)
                return a, v, short_video_metrics(reaction)
            from app.services.agent_memory import remember_block
            personal = "\nWhat's on your mind today:\n" + "\n".join(x.get("title", "") for x in a.cfg.get("personal_signals", []))
            personal += remember_block(self.cfg.get("agent_memory", {}).get("snapshots", {}).get(a.ref, []))
            history_state = self.cfg.get("agent_memory", {}).get("affinity", {}).get("people", {}).get(str(idx), {})
            if history_state:
                personal += "\nYour simulated creator history (small familiarity/affinity effects; fatigue reduces novelty): " + json.dumps(history_state)
            d = await self.llm.complete_json(system=systems[v], user=persona_text(a.persona, plab) + personal + "\n\nReact now.", role="voice",
                                             max_tokens=700, usage=self.usage)
            normalized = norm_reaction(d, len(c["segments"]), len(c.get("poll_options") or []))
            normalized.update({k: d[k] for k in ("rewatch_probability", "stitch_duet_likelihood", "sound_reuse_likelihood", "comment_bait") if k in d})
            return a, v, short_video_metrics(normalized)

        tasks = [asyncio.create_task(react(a, v)) for a in voices for v in cards]
        done = 0
        try:
            for fut in asyncio.as_completed(tasks):
                try:
                    a, v, r = await fut
                except LLMAuthError:
                    raise
                except Exception as exc:
                    self.failures.append(str(exc)[:200])
                    if len(self.failures) > max(6, len(tasks) * 0.5):
                        raise LLMError(f"Too many failed agent calls ({len(self.failures)}). Last: {self.failures[-1]}")
                    continue
                done += 1
                if v == "B":
                    a.reaction = {**(a.reaction or {}), "B": r}
                    await self.emit("reaction", {"agent": a.ref, "variant": "B", "r": _brief(r) | {"influence": _influence(r, a.followers)}, "progress": [done, len(tasks)]})
                    continue
                a.reaction = {**r, **({"B": a.reaction["B"]} if a.reaction and "B" in a.reaction else {})}
                a.opinion = a.initial = r["score"]
                a.trajectory.append([0, r["score"]])
                a.memory.append(f"You saw the creator's content and thought: \"{r['quote']}\" ({r['score']:.1f}/10)")
                acts = await self.initial_actions(a, r)
                await self.emit("reaction", {"agent": a.ref, "variant": "A", "r": _brief(r) | {"influence": _influence(r, a.followers)}, "actions": acts, "progress": [done, len(tasks)]})
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
        reacted = [a for a in voices if a.reaction and "score" in a.reaction]
        if len(reacted) < max(5, len(voices) * 0.3):
            raise LLMError(f"Only {len(reacted)} voice agents answered. Last error: {self.failures[-1] if self.failures else 'unknown'}")
        for a in self.agents.values():
            if a.kind == "stakeholder":
                a.opinion = a.initial = {"supportive": 7.5, "opposing": 3.0}.get(a.persona.get("stance"), 5.0)
                a.trajectory.append([0, a.opinion])
        async with session_scope() as s:
            for a in reacted:
                await s.execute(update(SimAgent).where(SimAgent.id == a.id).values(reaction=a.reaction))
        self.fit_first(reacted)
        self.init_crowd()
        await self.end_round()

    async def initial_actions(self, a: AgentRT, r: dict) -> list[dict]:
        pls = [p for p in self.enabled if a.cfg["platform_weights"].get(p, 0) > 0.2] or self.enabled
        pl = pls[int(self.rng.integers(0, len(pls)))]
        target = self.creator[pl]
        out = []
        async with session_scope() as s:
            if r["score"] >= 6.5 or (self.rng.random() < 0.3 and r["score"] >= 5):
                act = "LIKE" if pl == "feed" else "UPVOTE"
                self.apply_vote(self.posts[target], act)
                self.log_action(s, a, pl, act, target_post=target)
                out.append({"type": act, "platform": pl, "target": target})
            elif pl == "forum" and r["score"] < 3.5 and self.rng.random() < 0.5:
                self.apply_vote(self.posts[target], "DOWNVOTE")
                self.log_action(s, a, pl, "DOWNVOTE", target_post=target)
                out.append({"type": "DOWNVOTE", "platform": pl, "target": target})
            if r["quote"] and self.rng.random() < max(r["would_comment"], 0.25):
                p = await self.new_post(s, pl, "comment", a.ref, a.name, a.region, r["quote"], r["score"], parent=target)
                self.log_action(s, a, pl, "COMMENT", post_id=p.id, target_post=target, content=r["quote"])
                self.graph_post(a, p, "commented_on", target)
                out.append({"type": "COMMENT", "platform": pl, "post_id": p.id, "target": target, "content": r["quote"]})
            if pl == "feed" and self.rng.random() < r["would_share"] * 0.6:
                p = await self.new_post(s, pl, "repost", a.ref, a.name, a.region, "", r["score"], parent=target)
                self.posts[target].reposts += 1
                self.log_action(s, a, pl, "REPOST", post_id=p.id, target_post=target)
                self.writer.edge(f"agent:{a.ref}", f"post:{target}", "reposted", "", round=0)
                out.append({"type": "REPOST", "platform": pl, "target": target})
        a.actions += len(out)
        return out

    def apply_vote(self, p: PostRT, act: str):
        if act == "LIKE":
            p.likes += 1
        elif act == "UPVOTE":
            p.up += 1
        elif act == "DOWNVOTE":
            p.down += 1
        p.dirty = True

    def graph_post(self, a: AgentRT, p: PostRT, rel: str, target: int | None):
        self.writer.node(f"post:{p.id}", "post", p.content[:80] or p.kind, f"{p.kind} · {p.platform}", p.content[:300],
                         platform=p.platform, author=a.handle, stance=p.stance)
        self.writer.edge(f"agent:{a.ref}", f"post:{p.id}", "wrote", "")
        if target is not None and f"post:{target}" in self.writer.known:
            self.writer.edge(f"post:{p.id}", f"post:{target}", rel, p.content[:200])
            tgt = self.posts.get(target)
            if tgt and tgt.author_ref in self.agents:
                self.writer.edge(f"agent:{a.ref}", f"agent:{tgt.author_ref}", "replied_to", p.content[:200])

    # ---- crowd ----------------------------------------------------------------------------------------------
    def fit_first(self, reacted: list[AgentRT]):
        n_seg = len(self.card["segments"])
        self.targets = BASE_TARGETS + [f"seg{k}" for k in range(n_seg)]
        ids = np.array([int(a.ref[2:]) for a in reacted])
        Y = np.array([[a.reaction[t] if not t.startswith("seg") else a.reaction["segment_engagement"][int(t[3:])] for t in self.targets]
                      for a in reacted], dtype=np.float64)
        self.history = self.cfg.get("agent_memory", {}).get("affinity")
        self.X0 = projection.design(self.pop, ids, self.topic_vec, self.platform_key, self.history, exact=True)
        self.ids0 = ids
        self.Y0 = Y
        self.surface0 = projection.fit(self.X0, Y, self.targets, self.seed)
        self.surface0.history = self.history

    def init_crowd(self):
        n = int(self.cfg["agents"]["crowd"])
        mask = self.pop.mask(self.audience)
        voice_ids = [int(a.ref[2:]) for a in self.agents.values() if a.kind == "voice"]
        mask[voice_ids] = False
        pool = np.flatnonzero(mask)
        self.crowd_idx = np.sort(self.rng.choice(pool, min(n, pool.size), replace=False)) if n > 0 and pool.size else np.array([], dtype=np.int64)
        if n > 0 and pool.size and self.audience.get("follower_split"):
            self.crowd_idx, _ = weighted_sample(self.pop, mask, n, self.rng, self.audience["follower_split"])
        if self.crowd_idx.size == 0:
            return
        P = projection.project_idx(self.pop, self.surface0, self.crowd_idx, self.topic_vec, self.platform_key, noise_seed=99)
        self.c_op = P[:, 0].astype(np.float32)
        self.c_op0 = self.c_op.copy()
        self.c_share = P[:, 1].astype(np.float32)
        if self.card.get("format_key") == "short_video" and self.platform_key in ("tiktok", "instagram", "youtube"):
            self.c_share = np.clip(self.c_share * (1 + self.c_op0 / 10 * .35 + self.c_share * .12), 0, 1)
        ex = self.pop.ocean[self.crowd_idx, 2].astype(np.float32)
        sc = self.pop.screen[self.crowd_idx].astype(np.float32)
        st = self.pop.stance[self.crowd_idx]
        self.c_act = np.clip(0.08 + 0.45 * ex * sc, 0.02, 0.8) * np.where(st == STANCES.index("disengaged"), 0.5, 1.0)
        self.c_contrarian = st == STANCES.index("contrarian")
        self.c_region = self.pop.region[self.crowd_idx].astype(np.int64)
        reddit = ((self.pop.platforms[self.crowd_idx] >> PLATFORMS.index("reddit")) & 1).astype(bool)
        self.c_forum = reddit | (self.rng.random(self.crowd_idx.size) < 0.15)
        self.c_exposed_creator = 0
        self.c_reposts_creator = 0
        codes = [r["code"] for r in REGIONS]
        for k in np.unique(self.c_region):
            n_k = int((self.c_region == k).sum())
            self.writer.node(f"crowd:{codes[k]}", "crowd", f"Crowd · {REGIONS[k]['city']}", "crowd", f"{n_k:,} population agents",
                             region=codes[k], size=n_k)
            self.writer.edge(f"crowd:{codes[k]}", f"region:{codes[k]}", "lives_in", "")

    def crowd_step(self) -> dict:
        if getattr(self, "crowd_idx", np.array([])).size == 0:
            return {}
        codes = [r["code"] for r in REGIONS]
        hour_mult = np.array([region(c)["curve"][self.local(c, self.round).hour] for c in codes], dtype=np.float32)
        active = self.rng.random(self.crowd_idx.size) < self.c_act * hour_mult[self.c_region]
        k_exp = int(self.cfg["behaviour"].get("crowd_exposures", 4))
        agg = defaultdict(lambda: Counter())
        stats = Counter()
        for pl in self.enabled:
            pids = [pid for pid in self.by_platform[pl][-400:] if self.posts[pid].kind != "repost"]
            if not pids:
                continue
            posts = [self.posts[pid] for pid in pids]
            rec = np.array([math.exp(-(self.round - p.round) / 5.0) for p in posts])
            pop_ = np.array([p.popularity() for p in posts])
            base_w = 0.6 * rec + 0.8 * pop_ + np.array([1.2 if p.author_ref in ("creator", "event") else 0.0 for p in posts]) + 0.05
            stance = np.array([np.nan if p.stance is None else p.stance for p in posts], dtype=np.float32)
            is_creator = np.array([p.author_ref == "creator" for p in posts])
            auth_reg = np.array([p.author_region for p in posts])
            on_pl = active & (self.c_forum if pl == "forum" else ~self.c_forum | (self.rng.random(self.crowd_idx.size) < 0.3))
            for k in np.unique(self.c_region[on_pl]):
                who = np.flatnonzero(on_pl & (self.c_region == k))
                if who.size == 0:
                    continue
                w = base_w * np.where(auth_reg == codes[k], 1.6, 1.0)
                w = w / w.sum()
                exp_idx = self.rng.choice(len(posts), size=(who.size, min(k_exp, len(posts))), p=w)
                ag = np.repeat(who, exp_idx.shape[1])
                ps = exp_idx.ravel()
                op = self.c_op[ag]
                st = stance[ps]
                align = np.where(np.isnan(st), op / 10, 1 - np.abs(op - np.nan_to_num(st, nan=5.0)) / 10)
                creator_hit = is_creator[ps]
                like_p = np.clip(0.04 + 0.22 * align ** 2, 0, 0.6)
                like = self.rng.random(ps.size) < like_p
                rep = self.rng.random(ps.size) < np.where(creator_hit, self.c_share[ag] * 0.15, 0.02 * align)
                if pl == "forum":
                    down = (~like) & (self.rng.random(ps.size) < 0.10 * (1 - align))
                # bounded-confidence opinion drift toward agent posts' stances
                has = ~np.isnan(st)
                diff = np.nan_to_num(st, nan=0.0) - op
                close = has & (np.abs(diff) < 3.5)
                delta = np.where(close, 0.06 * diff, 0.0)
                delta = np.where(self.c_contrarian[ag] & has, -0.04 * diff, delta)
                np.add.at(self.c_op, ag, delta.astype(np.float32))
                self.c_exposed_creator += int(creator_hit.sum())
                self.c_reposts_creator += int((rep & creator_hit).sum())
                for j in np.unique(ps):
                    sel = ps == j
                    p = posts[j]
                    nl, nr = int(like[sel].sum()), int(rep[sel].sum())
                    p.views += int(sel.sum())
                    if pl == "forum":
                        p.up += nl
                        p.down += int(down[sel].sum())
                    else:
                        p.crowd_likes += nl
                        p.crowd_reposts += nr
                    p.dirty = True
                    if nl or nr:
                        agg[p.id]["like" if pl == "feed" else "upvote"] += nl
                        agg[p.id]["repost"] += nr
                        agg[p.id][f"r:{codes[k]}"] += nl + nr
                stats[pl + "_exposures"] += int(ps.size)
                stats[pl + "_likes"] += int(like.sum())
                stats[pl + "_reposts"] += int(rep.sum())
        np.clip(self.c_op, 0, 10, out=self.c_op)
        stats["active"] = int(active.sum())
        self.crowd_agg = agg
        return dict(stats)

    # ---- LLM agent turns ------------------------------------------------------------------------------------
    async def agent_turn(self, a: AgentRT):
        weights = {p: a.cfg["platform_weights"].get(p, 0.3) for p in self.enabled}
        tot = sum(weights.values())
        pl = self.rng.choice(list(weights), p=[w / tot for w in weights.values()])
        feed = self.recommend(a, pl, self.cfg["platforms"][pl].get("feed_size", 6))
        views = [self.post_view(p) for p in feed]
        for p in feed:
            a.seen.add(p.id)
            p.views += 1
        if self.dry:
            await asyncio.sleep(DRY_PACE / max(self.speed, 0.1))
            out = dry.action(a, views, pl, np.random.default_rng([self.seed, a.id, self.round]))
        else:
            clock = self.local(a.region, self.round).strftime("%a %H:%M")
            ptxt = persona_text(a.persona, platform_label(self.platform_key)) if a.kind == "voice" else (
                f"{a.name} (@{a.handle}), a {a.persona.get('role', 'account')} account based in {region(a.region)['city']}.\n"
                f"{a.persona.get('description', '')}\nPublic stance toward the content: {a.persona.get('stance', 'neutral')}.")
            from app.services.agent_memory import remember_block
            remembered = self.cfg.get("agent_memory", {}).get("snapshots", {}).get(a.ref, [])
            remembered = remembered + [m for m in self.cfg.get("agent_memory", {}).get("opinion_snapshots", {}).get(a.ref, [])
                                      if m["id"] not in {x["id"] for x in remembered}]
            ptxt += remember_block(remembered)
            out = await self.llm.complete_json(system=self.system_action, role="action", max_tokens=500, usage=self.usage,
                                               user=action_user(ptxt, a.opinion, a.memory, clock, pl, views, self.breaking))
        return a, pl, views, out

    async def apply_turn(self, a: AgentRT, pl: str, views: list[dict], out: dict) -> list[dict]:
        allowed = FEED_ACTIONS if pl == "feed" else FORUM_ACTIONS
        valid_ids = {v["id"] for v in views} | a.discoveries
        handles = {x.handle: x.ref for x in self.agents.values()}
        acts = out.get("actions") if isinstance(out.get("actions"), list) else []
        done = []
        async with session_scope() as s:
            for act in acts[: int(self.cfg["behaviour"].get("max_actions", 3))]:
                if not isinstance(act, dict):
                    continue
                t = str(act.get("type") or "").upper().replace(" ", "_")
                if t not in allowed or t == "DO_NOTHING":
                    continue
                pid = act.get("post_id")
                try:
                    pid = int(str(pid).strip("# ")) if pid not in (None, "", "null") else None
                except ValueError:
                    pid = None
                text = str(act.get("content") or "").strip()[:600]
                if t in ("COMMENT", "REPOST", "QUOTE", "LIKE", "UPVOTE", "DOWNVOTE", "LIKE_COMMENT", "DISLIKE_COMMENT") and pid not in valid_ids:
                    continue
                if pid is not None and t in ("COMMENT", "REPOST", "QUOTE", "LIKE", "UPVOTE", "DOWNVOTE", "LIKE_COMMENT", "DISLIKE_COMMENT"):
                    target = self.posts.get(pid)
                    if not target or target.platform != pl or target.author_ref in a.muted:
                        continue
                if t in ("LIKE_COMMENT", "DISLIKE_COMMENT"):
                    post = self.posts.get(pid)
                    if not post or post.kind != "comment" or post.platform != pl or post.author_ref in a.muted:
                        continue
                    previous = a.comment_votes.get(pid)
                    if previous == t:
                        continue
                    if previous == "LIKE_COMMENT":
                        post.likes -= 1
                    elif previous == "DISLIKE_COMMENT":
                        post.down -= 1
                    self.apply_vote(post, "LIKE" if t == "LIKE_COMMENT" else "DOWNVOTE")
                    a.comment_votes[pid] = t
                    self.log_action(s, a, pl, t, target_post=pid)
                    done.append({"type": t, "target": pid})
                elif t in ("SEARCH_POSTS", "SEARCH_USER", "VIEW_TRENDS", "REFRESH"):
                    query = str(act.get("query") or text or "")[:200]
                    if t == "SEARCH_POSTS":
                        result = self.search_posts(a, pl, query)
                    elif t == "SEARCH_USER":
                        result = self.search_users(a, query)
                    elif t == "VIEW_TRENDS":
                        result = [{"title": x.get("title"), "value": x.get("value"), "region": a.region}
                                  for x in (self.cfg.get("context", {}).get(a.region) or {}).get("trending", [])][:10]
                    else:
                        result = [self.post_view(p) for p in self.recommend(a, pl, 6)]
                    for item in result:
                        if isinstance(item.get("id"), int):
                            a.discoveries.add(item["id"])
                            valid_ids.add(item["id"])
                    note = json.dumps(result, ensure_ascii=False)[:2500]
                    a.memory.append(f"{t} {query}: {note}")
                    self.log_action(s, a, pl, t, content=query, meta={"results": result})
                    done.append({"type": t, "content": query, "results": result})
                elif t == "MUTE":
                    ref = handles.get(str(act.get("handle") or "").lstrip("@"))
                    if ref and ref != a.ref and ref not in a.muted:
                        a.muted.add(ref)
                        a.discoveries = {pid for pid in a.discoveries if self.posts[pid].author_ref != ref}
                        valid_ids = {pid for pid in valid_ids if self.posts[pid].author_ref != ref}
                        self.log_action(s, a, pl, t, target_ref=ref)
                        done.append({"type": t, "target_ref": ref})
                elif t in ("LIKE", "UPVOTE", "DOWNVOTE"):
                    self.apply_vote(self.posts[pid], t)
                    self.log_action(s, a, pl, t, target_post=pid)
                    if t != "DOWNVOTE":
                        self.writer.edge(f"agent:{a.ref}", f"post:{pid}", "liked" if t == "LIKE" else "upvoted", "")
                    done.append({"type": t, "target": pid})
                elif t in ("COMMENT", "QUOTE", "POST") and text:
                    kind = {"COMMENT": "comment", "QUOTE": "quote", "POST": "post"}[t]
                    p = await self.new_post(s, pl, kind, a.ref, a.name, a.region, text, a.opinion, parent=pid if t != "POST" else None)
                    self.log_action(s, a, pl, t, post_id=p.id, target_post=pid, content=text)
                    self.graph_post(a, p, {"comment": "commented_on", "quote": "quoted"}.get(kind, "about"), pid)
                    if kind == "post":
                        self.writer.edge(f"post:{p.id}", "content:A", "discusses", text[:200])
                    done.append({"type": t, "post_id": p.id, "target": pid, "content": text})
                elif t == "REPOST" and pid is not None:
                    p = await self.new_post(s, pl, "repost", a.ref, a.name, a.region, "", a.opinion, parent=pid)
                    self.posts[pid].reposts += 1
                    self.log_action(s, a, pl, t, post_id=p.id, target_post=pid)
                    self.writer.edge(f"agent:{a.ref}", f"post:{pid}", "reposted", "")
                    done.append({"type": t, "target": pid})
                elif t == "FOLLOW":
                    ref = handles.get(str(act.get("handle") or "").lstrip("@"))
                    if ref and ref != a.ref and ref not in a.following:
                        a.following.add(ref)
                        self.agents[ref].followers += 1
                        self.log_action(s, a, pl, t, target_ref=ref)
                        self.writer.edge(f"agent:{a.ref}", f"agent:{ref}", "follows", "")
                        done.append({"type": t, "target_ref": ref})
        new_op = _f(out.get("opinion"), a.opinion, 0, 10)
        a.opinion = round(a.opinion + float(np.clip(new_op - a.opinion, -2.0, 2.0)), 2)
        a.trajectory.append([self.round, a.opinion])
        a.actions += len(done)
        summary = "; ".join(f"{d['type'].lower()}" + (f" \"{d['content'][:60]}\"" if d.get("content") else "") for d in done) or "scrolled"
        a.memory.append(f"{self.local(a.region, self.round).strftime('%H:%M')} on the {pl}: {summary}")
        a.memory = a.memory[-8:]
        return done

    # ---- round orchestration ------------------------------------------------------------------------------
    def round_meta(self, r: int) -> dict:
        return {"round": r, "rounds": self.rounds, "sim_time": self.sim_time(r).isoformat(),
                "clocks": {c: self.local(c, r).strftime("%a %H:%M") for c in self.cfg.get("regions", [])}}

    async def handle_control(self):
        for cmd in await jobs.drain_control(self.sim_id):
            c = cmd.get("cmd")
            if c == "stop":
                raise Stopped()
            if c == "speed":
                self.speed = _f(cmd.get("value"), 1.0, 0.1, 10)
            if c == "inject" and cmd.get("text"):
                await self.inject(str(cmd["text"])[:400], source="user")
            if c == "pause":
                await self.set_status("paused")
                await self.emit("simulation.paused", {"round": self.round})
                while True:
                    await asyncio.sleep(1.0)
                    more = await jobs.drain_control(self.sim_id)
                    if any(x.get("cmd") == "stop" for x in more):
                        raise Stopped()
                    for x in more:
                        if x.get("cmd") == "inject" and x.get("text"):
                            await self.inject(str(x["text"])[:400], source="user")
                    if any(x.get("cmd") == "resume" for x in more):
                        break
                await self.set_status("running")
                await self.emit("simulation.resumed", {"round": self.round})

    async def inject(self, text: str, source: str):
        async with session_scope() as s:
            for pl in self.enabled:
                p = await self.new_post(s, pl, "event", "event", "Breaking", "*", text, None)
                self.writer.node(f"post:{p.id}", "post", text[:80], "event", text, platform=pl, source=source)
                self.writer.edge(f"post:{p.id}", "content:A", "context_for", text[:200])
                self.log_action(s, None, pl, "EVENT", post_id=p.id, content=text, actor_ref="event", actor_name="Breaking")
        self.breaking.append(text)
        for a in self.agents.values():
            a.memory.append(f"Breaking: {text}")
        await self.emit("event.injected", {"round": self.round, "text": text, "source": source})

    async def set_status(self, status: str):
        async with session_scope() as s:
            await s.execute(update(Simulation).where(Simulation.id == self.sim_id).values(status=status))

    async def run_round(self, r: int):
        self.round = r
        self.breaking = []
        self.writer.round = r
        for ev in self.cfg["events"].get("scheduled", []):
            if int(ev.get("round", -1)) == r:
                await self.inject(ev["text"], source=ev.get("source", "scheduled"))
        await self.handle_control()
        await self.emit("round.start", self.round_meta(r))
        llm_agents = [a for a in self.agents.values() if a.reaction or a.kind == "stakeholder"]
        active = [a for a in llm_agents if self.rng.random() < a.cfg["activity"] * self.curve(a.region, r)]
        tasks = [asyncio.create_task(self.agent_turn(a)) for a in active]
        try:
            for fut in asyncio.as_completed(tasks):
                try:
                    a, pl, views, out = await fut
                except LLMAuthError:
                    raise
                except Exception as exc:
                    self.failures.append(str(exc)[:200])
                    continue
                if out is None:
                    continue
                done = await self.apply_turn(a, pl, views, out)
                if done:
                    await self.emit("actions", {"round": r, "agent": a.ref, "name": a.name, "handle": a.handle, "kind": a.kind,
                                                "region": a.region, "platform": pl, "opinion": a.opinion, "actions": done,
                                                "time": self.local(a.region, r).strftime("%H:%M")})
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
        crowd = self.crowd_step()
        await self.end_round(crowd, len(active))
        if self.dry and self.speed < 5:
            await asyncio.sleep(0.25 / self.speed)

    async def end_round(self, crowd: dict | None = None, active: int = 0):
        async with session_scope() as s:
            for p in self.posts.values():
                if p.dirty:
                    await s.execute(update(Post).where(Post.id == p.id).values(stats=p.stats()))
                    p.dirty = False
            for pid, c in (getattr(self, "crowd_agg", None) or {}).items():
                regs = {k[2:]: v for k, v in c.items() if k.startswith("r:")}
                for act in ("like", "upvote", "repost"):
                    if c.get(act):
                        pl = self.posts[pid].platform
                        self.log_action(s, None, pl, f"CROWD_{act.upper()}" + ("_COMMENT" if self.posts[pid].kind == "comment" and act in ("like", "upvote") else ""), target_post=pid, actor_ref="crowd",
                                        actor_name="Crowd", meta={"count": int(c[act]), "regions": regs})
                for code, v in regs.items():
                    if v >= 3 and f"post:{pid}" in self.writer.known:
                        self.writer.edge(f"crowd:{code}", f"post:{pid}", "engaged", f"{v} crowd interactions", weight=float(v))
        self.crowd_agg = {}
        vo = [a.opinion for a in self.agents.values() if a.kind == "voice" and a.initial is not None]
        top = sorted((p for p in self.posts.values() if p.kind in ("post", "comment", "quote", "external")),
                     key=lambda p: -(p.popularity() + 0.001 * p.views))[:5]
        creator_views = sum(self.posts[pid].views for pid in getattr(self, "creator", {}).values())
        m = {"round": self.round, "sim_time": self.sim_time(self.round).isoformat(), "active_agents": active,
             "voice_opinion": round(float(np.mean(vo)), 3) if vo else None,
             "crowd_opinion": round(float(self.c_op.mean()), 3) if getattr(self, "c_op", None) is not None else None,
             "polarization": round(float(np.std(vo)), 3) if vo else None,
             "posts": len(self.posts), "creator_views": int(creator_views),
             "actions": {f"{k[0]}:{k[1]}": v for k, v in self.counts.items()}, "crowd": crowd or {},
             "by_region": {c: round(float(np.mean([a.opinion for a in self.agents.values() if a.region == c and a.kind == "voice"] or [np.nan])), 2)
                           for c in self.cfg.get("regions", [])},
             "top_posts": [{"id": p.id, "platform": p.platform, "author": p.author_name, "content": p.content[:140], **p.stats()} for p in top]}
        m["by_region"] = {k: (None if v != v else v) for k, v in m["by_region"].items()}
        self.timeline.append(m)
        from app.services.knowledge.learn import learn_round
        await learn_round(self.writer, [{"id": p.id, "author_ref": p.author_ref, "content": p.content[:2000],
                                        "kind": p.kind} for p in self.posts.values()
                                       if p.round == self.round and p.author_ref in self.agents
                                       and p.kind in ("post", "comment", "quote")], self.llm, self.usage)
        await self.writer.flush(f"round {self.round}")
        await self.emit("round.end", m)
        async with session_scope() as s:
            await s.execute(update(Simulation).where(Simulation.id == self.sim_id).values(progress={
                "round": self.round, "rounds": self.rounds, "posts": len(self.posts), "actions": int(sum(self.counts.values())),
                "sim_time": self.sim_time(self.round).isoformat(), "voice_opinion": m["voice_opinion"], "crowd_opinion": m["crowd_opinion"]}))

    async def run(self) -> dict:
        await self.load()
        self.system_action = action_system(card_block(self.card)[:3000], self.world_block, self.cfg.get("analysis_focus", ""))
        t0 = time.time()
        stopped = False
        await self.first_exposure()
        try:
            for r in range(1, self.rounds + 1):
                await self.run_round(r)
        except Stopped:
            stopped = True
            await self.emit("simulation.stopping", {"round": self.round})
        async with session_scope() as s:
            for a in self.agents.values():
                await s.execute(update(SimAgent).where(SimAgent.id == a.id).values(
                    state={"opinion": a.opinion, "initial": a.initial, "trajectory": a.trajectory, "actions": a.actions,
                           "following": sorted(a.following), "muted": sorted(a.muted), "comment_votes": a.comment_votes, "memory": a.memory[-8:]}, followers=a.followers))
        from .analytics import finalize
        results = await asyncio.to_thread(finalize, self)
        results["runtime_seconds"] = round(time.time() - t0, 1)
        results["stopped_early"] = stopped
        return results


def _influence(r: dict, followers: int) -> float:
    """Chance this person's reaction moves others: share intent weighted by how far their voice carries."""
    reach = min(1.0, math.log10(max(followers, 1) + 10) / 5)
    return round(float(r.get("would_share", 0)) * reach, 3)


def _brief(r: dict) -> dict:
    return {k: r.get(k) for k in ("score", "sentiment", "primary_emotion", "quote", "would_share", "would_comment", "drop_segment",
                                  "objection", "drivers", "reason")}
