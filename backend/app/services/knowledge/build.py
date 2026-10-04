"""Step 1 · Graph build: ontology → entity/relation extraction → live data-pool linkage.

The graph is emitted incrementally (one flush per extracted chunk) so the UI grows it in real time."""
from __future__ import annotations

import asyncio
import json
import re

from app.services.content.card import heuristic_entities
from app.services.datapool.context import tokens
from app.services.llm import BaseLLM, LLMAuthError, Usage
from app.services.population.regions import INTEREST_LABELS

from .store import GraphWriter, slug

DEFAULT_ONTOLOGY = {
    "entity_types": [
        {"name": "Person", "description": "A named individual, creator or public figure"},
        {"name": "Organization", "description": "Company, institution, government body"},
        {"name": "Brand", "description": "Commercial brand or product line"},
        {"name": "Product", "description": "A specific product or service"},
        {"name": "Place", "description": "City, country, venue"},
        {"name": "Event", "description": "Occasion, holiday, incident, launch"},
        {"name": "Topic", "description": "Theme or subject of discussion"},
        {"name": "Claim", "description": "A factual or persuasive assertion in the content"},
        {"name": "MediaOutlet", "description": "News source or media account"},
        {"name": "Audience", "description": "A group of people the content addresses"},
    ],
    "relation_types": [
        {"name": "mentions", "description": "content or entity references another"},
        {"name": "promotes", "description": "endorses or advertises"},
        {"name": "criticizes", "description": "speaks against"},
        {"name": "competes_with", "description": "rival brands or products"},
        {"name": "located_in", "description": "geographic relation"},
        {"name": "part_of", "description": "membership or composition"},
        {"name": "related_to", "description": "generic association"},
        {"name": "targets", "description": "addresses an audience"},
    ],
    "analysis_focus": "How different audiences will react to the content and why.",
}

ONTOLOGY_SYSTEM = """You design the ontology for a knowledge graph that will ground a social-media audience simulation.
Given the user's question, the content and any background documents, choose the entity types and relation types that
matter for predicting audience reaction (brands, people, places, claims, events, competitors, communities...).
Return JSON:
{"entity_types": [{"name": "PascalCase", "description": "..."} (6-10 items)],
 "relation_types": [{"name": "snake_case", "description": "..."} (6-12 items)],
 "analysis_focus": "one sentence: what the simulation should pay attention to"}"""

EXTRACT_SYSTEM = """You extract a knowledge graph from text for a social-media audience simulation.
Use ONLY these entity types: {etypes}
and ONLY these relation types: {rtypes}
Rules: entity names exactly as written (keep Arabic as Arabic); at most 15 entities and 20 relations; summary = one
factual sentence; fact = one sentence stating the relation as the text supports it. Skip generic words.
Return JSON: {{"entities": [{{"name": "...", "type": "...", "summary": "..."}}],
 "relations": [{{"source": "<entity name>", "target": "<entity name>", "relation": "...", "fact": "..."}}]}}"""


def chunk(text: str, size: int = 1800) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n{2,}|(?<=[.!?؟])\s+", text) if p.strip()]
    out, cur = [], ""
    for p in paras:
        if len(cur) + len(p) > size and cur:
            out.append(cur)
            cur = ""
        cur += (" " if cur else "") + p
    if cur:
        out.append(cur)
    return out


async def generate_ontology(requirement: str, card: dict, seeds: list[tuple[str, str]], llm: BaseLLM, usage: Usage) -> dict:
    if llm.is_dry:
        return {**DEFAULT_ONTOLOGY, "by": "dry-run default"}
    user = json.dumps({"question": requirement, "content": {"title": card.get("title"), "summary": card.get("summary"),
                                                            "entities": card.get("entities"), "keywords": card.get("keywords")},
                       "background": [{"name": n, "excerpt": t[:1500]} for n, t in seeds[:4]]}, ensure_ascii=False)
    try:
        d = await llm.complete_json(system=ONTOLOGY_SYSTEM, user=user, role="ontology", max_tokens=1500, usage=usage, temperature=0.2)
        ets = [e for e in d.get("entity_types", []) if isinstance(e, dict) and e.get("name")][:12]
        rts = [r for r in d.get("relation_types", []) if isinstance(r, dict) and r.get("name")][:14]
        if len(ets) >= 3 and len(rts) >= 3:
            return {"entity_types": ets, "relation_types": rts, "analysis_focus": str(d.get("analysis_focus") or ""),
                    "by": llm.model_for("ontology")}
    except LLMAuthError:
        raise
    except Exception:
        pass
    return {**DEFAULT_ONTOLOGY, "by": "default (model output unusable)"}


_PLACES = {"dubai", "abu dhabi", "riyadh", "jeddah", "cairo", "amman", "casablanca", "london", "new york", "mumbai", "uae", "saudi arabia",
           "egypt", "jordan", "morocco", "india", "gulf", "doha", "kuwait", "bahrain"}
_EVENTS = {"ramadan", "eid", "christmas", "diwali", "national day"}


def _dry_type(name: str) -> str:
    low = name.lower()
    if low in _PLACES:
        return "Place"
    if low in _EVENTS:
        return "Event"
    if re.search(r"[a-z][A-Z]", name) or re.search(r"\b(Inc|Ltd|Co|Group|Gym|Bank|Media|News|Club)\b", name):
        return "Brand"
    return "Organization" if " " in name else "Topic"


def _dry_extract(text: str, known: list[str]) -> dict:
    ents = {}
    for m in heuristic_entities(text, 15):
        ents.setdefault(m, {"name": m, "type": _dry_type(m), "summary": "[dry run] mentioned in source"})
    for k in known:
        if k and k not in ents and re.search(r"\b" + re.escape(k) + r"\b", text, re.I):
            ents[k] = {"name": k, "type": _dry_type(k) if k[:1].isupper() else "Topic", "summary": "[dry run] keyword"}
    names = list(ents)[:15]
    rels = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        present = [n for n in names if n in sent]
        for a, b in zip(present, present[1:]):
            rels.append({"source": a, "target": b, "relation": "related_to", "fact": sent[:240]})
    return {"entities": [ents[n] for n in names], "relations": rels[:20]}


async def extract(text: str, ontology: dict, llm: BaseLLM, usage: Usage, known: list[str]) -> dict:
    if llm.is_dry:
        return _dry_extract(text, known)
    etypes = ", ".join(e["name"] for e in ontology["entity_types"])
    rtypes = ", ".join(r["name"] for r in ontology["relation_types"])
    try:
        d = await llm.complete_json(system=EXTRACT_SYSTEM.format(etypes=etypes, rtypes=rtypes), user=text, role="extract",
                                    max_tokens=2500, usage=usage, temperature=0.1)
        return {"entities": [e for e in d.get("entities", []) if isinstance(e, dict) and e.get("name")][:20],
                "relations": [r for r in d.get("relations", []) if isinstance(r, dict) and r.get("source") and r.get("target")][:30]}
    except LLMAuthError:
        raise
    except Exception:
        return _dry_extract(text, known)


async def build(sim_id: str, requirement: str, cards: dict, seeds: list[tuple[str, str]], snaps: dict,
                llm: BaseLLM, usage: Usage, progress) -> dict:
    g = GraphWriter(sim_id, -1)
    await g.load_existing()
    # 1 · the content itself
    for v, card in cards.items():
        g.node(f"content:{v}", "content", card["title"] + (f" ({v})" if len(cards) > 1 else ""), card.get("type", "content"),
               card.get("summary", ""), platform=card.get("platform"), variant=v)
        for t, w in (card.get("topics") or {}).items():
            g.node(f"topic:{t}", "entity", INTEREST_LABELS.get(t, t), "Topic", f"Content topic ({INTEREST_LABELS.get(t, t)})")
            g.edge(f"content:{v}", f"topic:{t}", "about", f"The content is about {INTEREST_LABELS.get(t, t)}", weight=float(w))
    await g.flush("content analysed")
    await progress("Content card ready", 0.15)

    # 2 · live context from the data pool
    for code, snap in snaps.items():
        rk = g.node(f"region:{code}", "region", f"{snap['city']} · {snap['name']}", "Region", snap.get("brief", ""),
                    weather=snap.get("weather"), local_time=snap.get("local_time"), tone=snap.get("tone"))
        for n in snap.get("news", [])[:5]:
            sk = g.node(f"sig:news:{slug(n['title'])[:80]}", "signal", n["title"], "Headline", n.get("source", ""), url=n.get("url"),
                        source_id=n.get("source_id"), source_signal_id=n.get("id"), provenance=n.get("provenance"), language=n.get("language"))
            g.edge(rk, sk, "current_headline", n["title"])
        for t in snap.get("trending", [])[:3]:
            sk = g.node(f"sig:trend:{slug(t['title'])[:80]}", "signal", t["title"], "Trending", "Most-read page",
                        source_id=t.get("source_id"), source_signal_id=t.get("id"), provenance=t.get("provenance"))
            g.edge(rk, sk, "trending_in", f"{t['title']} is among the most read pages")
        for e in snap.get("events", [])[:2]:
            sk = g.node(f"sig:event:{slug(e['name'])}:{code}", "signal", e["name"], "Event", f"in {e.get('days_away')} days",
                        source_id=e.get("source_id"), source_signal_id=e.get("id"), provenance=e.get("provenance"), observation_id=e.get("observation_id"))
            g.edge(rk, sk, "upcoming", f"{e['name']} in {e.get('days_away')} days")
        for t in snap.get("social", [])[:4]:
            sk = g.node(f"sig:social:{slug(t['title'])[:80]}", "signal", t["title"], "SocialTrend", t.get("platform") or "",
                        source_id=t.get("source_id"), source_signal_id=t.get("id"), provenance=t.get("provenance"))
            g.edge(rk, sk, "social_trend", f"Trending on {t.get('platform')}")
        for v in cards:
            g.edge(f"content:{v}", rk, "shown_in", f"Content distributed to {snap['name']}")
    await g.flush("live data pool linked")
    await progress("Live context linked", 0.3)

    # 3 · ontology
    ontology = await generate_ontology(requirement, cards["A"], seeds, llm, usage)
    await progress("Ontology generated", 0.4)

    # 4 · extraction, one flush per chunk so the graph grows visibly
    texts = [("content", " ".join(s["text"] for s in cards["A"]["segments"]))]
    if "B" in cards:
        texts.append(("content_b", " ".join(s["text"] for s in cards["B"]["segments"])))
    for name, t in seeds:
        texts += [(name, c) for c in chunk(t)]
    texts = texts[:14]
    known = list(cards["A"].get("entities") or []) + list(cards["A"].get("keywords") or [])[:5]
    types = {e["name"] for e in ontology["entity_types"]}
    content_text = texts[0][1].lower()
    done = 0

    async def run(src: str, text: str):
        return src, text, await extract(text, ontology, llm, usage, known)

    for fut in asyncio.as_completed([run(s, t) for s, t in texts]):
        src, text, d = await fut
        names = {}
        for e in d["entities"]:
            nm = str(e["name"]).strip()[:200]
            typ = str(e.get("type") or "Topic")
            if typ not in types:
                typ = "Topic"
            key = g.node(f"ent:{slug(nm)}", "entity", nm, typ, str(e.get("summary") or ""), source=src)
            names[nm.lower()] = key
            if nm.lower() in content_text:
                g.edge("content:A", key, "mentions", f"The content mentions {nm}")
        for r in d["relations"]:
            a = names.get(str(r["source"]).lower()) or f"ent:{slug(str(r['source']))}"
            b = names.get(str(r["target"]).lower()) or f"ent:{slug(str(r['target']))}"
            if a in g.known and b in g.known:
                g.edge(a, b, str(r.get("relation") or "related_to")[:60], str(r.get("fact") or ""), source=src)
        done += 1
        await g.flush(f"extracted from {src}")
        await progress(f"Extracted {done}/{len(texts)} passages", 0.4 + 0.5 * done / len(texts))

    # 5 · connect entities to what is in the news right now
    ent_nodes = [k for k in g.known if k.startswith("ent:")]
    async with _labels(sim_id) as labels:
        for ek in ent_nodes:
            et = tokens(labels.get(ek, ""))
            if not et:
                continue
            for sk, lab in labels.items():
                if sk.startswith("sig:") and et & tokens(lab):
                    g.edge(ek, sk, "in_the_news", f"{labels[ek]} appears in: {lab}")
    await g.flush("entities linked to live signals")
    await progress("Graph complete", 1.0)
    return ontology


class _labels:
    def __init__(self, sim_id):
        self.sim_id = sim_id

    async def __aenter__(self):
        from sqlalchemy import select

        from app.db.session import session_scope
        from app.models import GraphNode
        async with session_scope() as s:
            rows = (await s.execute(select(GraphNode.key, GraphNode.label).where(GraphNode.simulation_id == self.sim_id))).all()
        return {k: lab for k, lab in rows}

    async def __aexit__(self, *a):
        return False
