"""Step 5 · Deep interaction: talk to any agent in character, or survey a whole segment."""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict

from app.services.content import card_block
from app.services.llm import BaseLLM, LLMAuthError, Usage
from app.services.population import persona_text, platform_label

CHAT_SYSTEM = """You are role-playing a specific person (or account) who took part in a social-media simulation run by Kruvim.
Answer the creator's questions in character, first person, consistent with your persona, your reaction to the content and
what you did during the simulation. Be honest and specific about what you liked, what lost you and why. Under 120 words
unless asked for more. Use your natural register. Do not mention being an AI or a simulation unless directly asked."""

SURVEY_SUMMARY = """You summarise answers from a survey of simulated audience members. Group the answers into 2-5 themes, count
how many answers fall in each, quote the most representative answer per theme, and finish with one sentence on what the
creator should do. Return JSON: {"themes": [{"theme": "...", "count": n, "quote": "..."}], "takeaway": "..."}"""


def context_for(detail: dict, card: dict, platform: str | None) -> str:
    p = detail.get("persona") or {}
    if detail.get("kind") == "stakeholder":
        who = (f"{detail.get('name')} (@{detail.get('handle')}), a {p.get('role', 'account')} account. {p.get('description', '')}\n"
               f"Public stance: {p.get('stance', 'neutral')}.")
    else:
        who = persona_text(p, platform_label(platform)) if p.get("ocean") else json.dumps(p)[:800]
    parts = [who, "", "=== THE CONTENT ===", card_block(card)[:3500], ""]
    from app.services.agent_memory import remember_block
    parts.append(remember_block((detail.get("long_term_memory") or {}).get("recalled", [])))
    r = detail.get("reaction") or {}
    st = detail.get("state") or {}
    if r.get("score") is not None:
        parts += ["=== YOUR FIRST REACTION ===", json.dumps({k: r.get(k) for k in ("score", "quote", "reason", "objection", "drop_segment",
                                                                                  "primary_emotion")}, ensure_ascii=False)]
    elif detail.get("projected"):
        parts += ["=== YOUR LIKELY REACTION (you were not interviewed; stay consistent) ===", json.dumps(detail["projected"])]
    if st.get("opinion") is not None:
        parts.append(f"Your opinion after the day of discussion: {st['opinion']:.1f}/10 (it started at {st.get('initial') or r.get('score')}).")
    posts = [x for x in detail.get("posts", []) if x.get("content")][-6:]
    if posts:
        parts += ["", "=== WHAT YOU POSTED ==="] + [f"- [{x['platform']} {x['kind']}] {x['content'][:200]}" for x in posts]
    if st.get("memory"):
        parts += ["", "=== YOUR RECENT MEMORY ==="] + [f"- {m}" for m in st["memory"][-5:]]
    return "\n".join(parts)


def dry_answer(detail: dict, question: str) -> str:
    r = detail.get("reaction") or detail.get("projected") or {}
    st = detail.get("state") or {}
    op = st.get("opinion", r.get("score", "?"))
    memories = (detail.get("long_term_memory") or {}).get("recalled", [])
    remembered = " My simulated memory: " + memories[0]["text"] if memories else ""
    return (f"[dry run] I'm {detail.get('name', 'this agent')} ({(detail.get('persona') or {}).get('city', '')}). "
            f"My take on the content is {op}/10.{remembered} Connect a model in Settings to get real in-character answers.")


async def ask(detail: dict, card: dict, platform: str | None, history: list[dict], question: str, llm: BaseLLM, usage: Usage) -> str:
    if llm.is_dry:
        return dry_answer(detail, question)
    convo = "\n".join(("Creator: " if h["role"] == "user" else "You: ") + h["content"] for h in history[-10:])
    text = await llm.complete(system=CHAT_SYSTEM + "\n\n" + context_for(detail, card, platform), role="chat", max_tokens=600, usage=usage,
                              json_out=False, user=(convo + "\n" if convo else "") + f"Creator: {question}\nYou:")
    return text.strip()


async def survey(details: list[dict], card: dict, platform: str | None, question: str, llm: BaseLLM, usage: Usage, on_answer=None) -> dict:
    semaphore = asyncio.Semaphore(max(1, min(32, llm.s.concurrency)))
    async def one(d):
        try:
            async with semaphore:
                a = await ask(d, card, platform, [], question, llm, usage)
        except LLMAuthError:
            raise
        except Exception as exc:
            a = f"(no answer: {exc.__class__.__name__})"
        item = {"agent": d["ref"], "name": d.get("name"), "region": d.get("region"), "stance": (d.get("persona") or {}).get("stance"),
                "opinion": (d.get("state") or {}).get("opinion"), "answer": a}
        if on_answer:
            await on_answer(item)
        return item

    answers = await asyncio.gather(*[one(d) for d in details])
    if llm.is_dry or not answers:
        return {"answers": answers, "summary": rule_summary(answers, dry=llm.is_dry)}
    batches = []
    try:
        for i in range(0, len(answers), 50):
            batch = answers[i:i + 50]
            batches.append(await llm.complete_json(system=SURVEY_SUMMARY, role="report", max_tokens=1200, usage=usage,
                user=json.dumps({"question": question, "answers": [a["answer"][:1000] for a in batch]}, ensure_ascii=False)))
        if len(batches) == 1:
            summ = batches[0]
        else:
            summ = await llm.complete_json(system=SURVEY_SUMMARY + " Merge the batch themes. Counts are respondent counts, not batch counts; do not count anyone twice.",
                role="report", max_tokens=1200, usage=usage, user=json.dumps({"question": question, "respondents": len(answers),
                "batches": [{"themes": [{"theme": str(t.get("theme", ""))[:100], "count": t.get("count"),
                "quote": str(t.get("quote", ""))[:120]} for t in b.get("themes", [])[:5]],
                "takeaway": str(b.get("takeaway", ""))[:200]} for b in batches]}, ensure_ascii=False))
        if not isinstance(summ.get("themes"), list):
            summ = rule_summary(answers)
    except LLMAuthError:
        raise
    except Exception:
        summ = rule_summary(answers)
    return {"answers": answers, "summary": summ}


def rule_summary(answers, dry=False):
    grouped = defaultdict(list)
    for a in answers:
        value = a.get("opinion")
        if a["answer"].startswith("(no answer:"):
            theme = "Unavailable answers"
        else:
            theme = "Unrated" if not isinstance(value, (float, int)) else "Positive reactions" if value >= 6.5 else "Negative reactions" if value < 4 else "Mixed reactions"
        grouped[theme].append(a)
    return {"themes": [{"theme": theme, "count": len(rows), "quote": rows[0]["answer"], "agent_refs": [a["agent"] for a in rows]}
                       for theme, rows in grouped.items()], "takeaway": "[dry run] Themed by simulated opinion; these are demonstration answers." if dry
                       else "Themes grouped by simulated opinion; review the individual answers before deciding.", "method": "rule-based"}
