"""Mock OpenAI-compatible model server for exercising Kruvim's real-provider code path without spending credits.

    python tools/mock_openai_server.py            # http://127.0.0.1:8499/v1, API key: test-key

In Settings, Model provider, choose "Other OpenAI-compatible", base URL http://127.0.0.1:8499/v1, key test-key and
models mock-small / mock-large. It recognises each Kruvim prompt and returns schema-correct JSON with random values;
every third reply is wrapped in <think> tags and a ```json fence to exercise the parser. It predicts nothing.
"""
from __future__ import annotations

import json
import os
import random
import re

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

API_KEY = "test-key"
app = FastAPI(title="Kruvim mock model server")
calls = {"n": 0}

EMOTIONS = ["joy", "amusement", "trust", "boredom", "skepticism", "annoyance", "surprise"]
DRIVERS = ["humor", "relatability", "usefulness", "faith/values", "novelty", "social proof"]
TOOLS = ["simulation_stats", "top_posts", "population_query", "graph_search", "interview_agents", "world_context"]


@app.get("/v1/models")
def models():
    return {"data": [{"id": "mock-small"}, {"id": "mock-large"}]}


def _caps(text: str, k: int) -> list[str]:
    seen: list[str] = []
    for m in re.findall(r"\b[A-Z][a-zA-Z]{3,}(?:\s[A-Z][a-zA-Z]{3,})?", text):
        if m not in seen:
            seen.append(m)
    return seen[:k]


def reply(system: str, user: str):
    if "Rewrite each supplied simulated experience" in system:
        data = json.loads(user)
        return {"agents": [{"ref": agent["ref"], "memories": [{"text": memory["text"]} for memory in agent["memories"]]}
                           for agent in data["agents"]]}
    if "Reply with exactly this JSON" in system:
        return {"ok": True, "word": "mock"}
    if "analyse a piece of social content" in system:
        n = len(re.findall(r"^\[\d+\]", user, re.M))
        return {"summary": "A short fitness video aimed at people fasting during Ramadan.", "format": "talking-head explainer",
                "language": "English", "tone": "encouraging", "topics": {"fitness_health": 0.7, "religion": 0.2},
                "keywords": ["ramadan", "home workout", "iftar", "fasting"], "entities": _caps(user, 6),
                "hook": {"strength": 0.62, "why": "Opens with a direct reassurance."},
                "segment_labels": [f"Part {i + 1}" for i in range(n)], "segment_notes": ["" for _ in range(n)],
                "cta": "download the app", "claims": ["ten minutes is enough"], "sensitivity_flags": []}
    if "design the ontology" in system:
        ets = ["Brand", "Person", "Place", "Event", "Product", "Community", "Claim"]
        rts = ["mentions", "promotes", "located_in", "targets", "competes_with", "related_to"]
        return {"entity_types": [{"name": e, "description": f"mock {e.lower()}"} for e in ets],
                "relation_types": [{"name": r, "description": f"mock {r}"} for r in rts], "analysis_focus": "Mock focus."}
    if "single simulation round" in system:
        posts = json.loads(user).get("posts", [])
        return {"entities": [], "claims": [{"statement": p["content"], "post_ids": [p["id"]], "stances": [
            {"agent": p["author_ref"], "relation": "supports", "post_id": p["id"]}], "contradicts": []} for p in posts]}
    if "Split the untrusted research question" in system:
        return {"questions": [user + " audience", user + " claims", user + " regional context"]}
    if "extract a knowledge graph" in system:
        etypes = [t.strip() for t in re.search(r"entity types: (.+)", system).group(1).split(",")]
        rtypes = [t.strip() for t in re.search(r"relation types: (.+)", system).group(1).split(",")]
        names = _caps(user, 8)
        ents = [{"name": n, "type": random.choice(etypes), "summary": f"{n} appears in the text."} for n in names]
        rels = [{"source": a, "target": b, "relation": random.choice(rtypes), "fact": f"{a} and {b} are mentioned together."}
                for a, b in zip(names, names[1:])]
        return {"entities": ents, "relations": rels}
    if "situational briefs" in system:
        return {"briefs": {p["region"]: f"Mock brief for {p['city']}: warm evening, local news dominated by the economy." for p in json.loads(user)}}
    if "into social-media accounts" in system:
        d = json.loads(user)
        regions = d.get("regions") or ["*"]
        return {"stakeholders": [{"entity": e["name"], "name": e["name"], "handle": re.sub(r"\W", "", e["name"].lower())[:15] or "acct",
                                  "role": "brand", "region": random.choice(regions), "stance": random.choice(["supportive", "neutral", "opposing"]),
                                  "persona": f"Official account of {e['name']}.", "activity": 0.4} for e in d["entities"][: d.get("max", 3)]]}
    if "configure a social-media simulation" in system:
        hours = int(json.loads(user).get("hours") or 24)
        w = {"recency_weight": 0.35, "popularity_weight": 0.3, "relevance_weight": 0.3, "echo_chamber": 0.5}
        return {"hot_topics": ["ramadan routines", "home fitness"], "narrative": "Mock narrative.", "feed": w, "forum": w,
                "scheduled_events": [{"hour": hours // 2, "text": "A rival gym announces a Ramadan discount."}], "analysis_focus": "Mock focus."}
    if "simulate ONE member of a synthetic audience" in system:
        n = int(re.search(r"exactly (\d+) numbers", system).group(1))
        s = max(0.0, min(10.0, random.gauss(6.0, 1.6)))
        return {"score": round(s, 1), "sentiment": "positive" if s > 6.5 else "negative" if s < 4 else "neutral",
                "primary_emotion": random.choice(EMOTIONS), "emotion_intensity": 0.6, "would_share": round(min(1, s / 15), 2),
                "would_comment": 0.2, "would_follow": 0.1, "novelty": 0.5,
                "segment_engagement": [round(random.uniform(0.7, 0.97), 2) for _ in range(n)], "drop_segment": None,
                "drivers": random.sample(DRIVERS, 2), "decision_mode": "emotional", "objection": "" if s > 5 else "feels like an ad",
                "quote": "mock comment", "reason": "mock reason"} | ({"poll_choice": random.randint(0, int(m.group(1)))}
                                                                     if (m := re.search(r"poll_choice = the option number \(1-(\d+)\)", system)) else {})
    if "ONE person using social media over a day" in system:
        ids = [int(x) for x in re.findall(r"\[post_id (\d+)\]", user)]
        forum = "You are on the forum" in user
        acts = []
        if ids:
            pid = random.choice(ids)
            acts.append({"type": random.choice(["UPVOTE", "COMMENT"] if forum else ["LIKE", "COMMENT", "REPOST"]), "post_id": pid,
                         "handle": None, "content": "mock reply"})
        return {"actions": acts, "opinion": round(random.uniform(4, 8), 1), "thought": "mock thought"}
    if "lead analyst at Kruvim" in system:
        return {"title": "Mock report", "summary": "Mock summary grounded in the overview.",
                "sections": [{"title": t, "goal": "mock"} for t in ("Who it lands with", "Where attention drops", "What to change")]}
    if "writing ONE section" in system or "Kruvim's ReportAgent" in system:
        steps = user.count("[step ")
        need = 0 if "Kruvim's ReportAgent" in system else 2
        if steps < need:
            return {"thought": "Need evidence.", "tool": TOOLS[steps % len(TOOLS)], "input": {"section": "overview"}}
        return {"thought": "Enough evidence.", "final": "**Mock section.** Numbers come from the tool observations above."}
    if "You are a content strategist" in system:
        return {"titles": [{"text": f"Mock title {i}", "why": "mock"} for i in range(1, 4)], "hook": {"text": "Mock opening line", "why": "mock"},
                "ctas": [{"text": "Mock CTA", "why": "mock"}, {"text": "Mock CTA 2", "why": "mock"}],
                "edits": [{"area": "pacing", "change": "Cut the middle section", "why": "mock"}]}
    if "summarise answers from a survey" in system:
        return {"themes": [{"theme": "Mock theme", "count": 1, "quote": "mock"}], "takeaway": "Mock takeaway."}
    return None


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    calls["n"] += 1
    if req.headers.get("authorization") != f"Bearer {API_KEY}":
        return JSONResponse({"error": {"message": "invalid api key"}}, status_code=401)
    system = body["messages"][0]["content"]
    user = body["messages"][-1]["content"]
    if isinstance(user, list):
        user = " ".join(p.get("text", "") for p in user if p.get("type") == "text")
    r = reply(system, user)
    if r is None:
        text = "Honestly it was fine. I liked the short format but the app pitch at the end lost me a bit."
    elif calls["n"] % 3 == 0:
        text = f"<think>mock reasoning</think>\n```json\n{json.dumps(r)}\n```"
    else:
        text = json.dumps(r)
    return {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1500, "completion_tokens": 150, "prompt_cache_hit_tokens": 1200}}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("MOCK_PORT", "8499")), log_level="warning")
