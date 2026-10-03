"""Step 4 · ReportAgent.

Plans an outline from the results, then writes each section with a ReAct loop (thought → tool → observation,
2-5 tool calls per section). Every thought, tool call and finished section is streamed as an event so the
user watches the analyst work. Provider-neutral: the loop speaks JSON, no native function calling needed."""
from __future__ import annotations

import copy
import json

from sqlalchemy.orm.attributes import flag_modified

from app.db.session import session_scope
from app.models import Report, Simulation
from app.services.events import bus
from app.services.llm import BaseLLM, LLMAuthError, Usage

from .tools import TOOL_SPECS, Toolbox

OUTLINE_SYSTEM = """You are the lead analyst at Kruvim, a synthetic-audience testing platform. A simulation just finished.
Plan a report that answers the user's question for a content creator or brand team. Use the overview to decide what
matters. Return JSON: {"title": "...", "summary": "2-3 sentence answer to the question, grounded in the overview numbers",
 "sections": [{"title": "...", "goal": "what this section must establish"} (3-5 sections)]}"""

REACT_SYSTEM = """You are writing ONE section of a Kruvim simulation report. Work in steps. At each step reply with JSON only:
either {{"thought": "...", "tool": "<tool name>", "input": {{...}}}} to gather evidence, or
{{"thought": "...", "final": "<the section text in Markdown>"}} when you have enough.
Tools:
{tools}
Rules:
- Use at least {min_calls} tools before writing; never more than {max_calls}.
- Every claim must come from tool observations. Cite numbers and quote simulated people with > blockquotes.
- Be specific and actionable for a content creator. No generic advice. No headings inside the section (use **bold**).
- 150-350 words."""

CHAT_SYSTEM = """You are Kruvim's ReportAgent. You already wrote the report below. Answer the user's follow-up questions using the
report first; call at most 2 tools when you need new evidence. Reply with JSON only: {{"thought": "...", "tool": "...", "input": {{...}}}}
or {{"thought": "...", "final": "<answer in Markdown, concise>"}}.
Tools:
{tools}

=== REPORT ===
{report}"""


OPTIMIZE_SYSTEM = """You are a content strategist. A piece of content was tested on a simulated audience. Using ONLY the evidence given
(objections, where attention dropped, who disliked it and why, what people quoted), propose concrete rewrites the creator
can test. Keep the creator's language and voice; do not invent facts about the product.
Return JSON: {"titles": [{"text": "...", "why": "evidence it addresses"} (3 items)],
 "hook": {"text": "a new opening line or first 3 seconds", "why": "..."},
 "ctas": [{"text": "...", "why": "..."} (2 items)],
 "edits": [{"area": "pacing|tone|claims|visuals|structure|audience", "change": "specific edit", "why": "evidence"} (2-4 items)]}"""


async def optimize(sim: Simulation, llm: BaseLLM, usage: Usage) -> dict | None:
    """Rewrite suggestions for the "Fix it" panel. Each one can be re-tested as version B with one click."""
    if llm.is_dry:
        return None
    r = sim.results or {}
    hm = r.get("heatmap") or {}
    evidence = {
        "title": (sim.card or {}).get("title"), "format": (sim.card or {}).get("format_label"), "platform": (sim.content or {}).get("platform"),
        "goal": (sim.content or {}).get("goal"), "summary": (sim.card or {}).get("summary"),
        "opening": ((sim.card or {}).get("segments") or [{}])[0].get("text", "")[:400],
        "objections": (r.get("psychology") or {}).get("objections", [])[:6],
        "attention_drops": [{"segment": s["i"] + 1, "label": s["label"], "lost": s["loss"], "quotes": [q["quote"] for q in s.get("drop_quotes", [])]}
                            for s in sorted(hm.get("segments") or [], key=lambda s: -s["loss"])[:3]],
        "resists": [{"group": g["label"], "score": g["score"], "quote": (g.get("evidence") or {}).get("quote")} for g in r.get("losers", [])[:3]],
        "loves": [{"group": g["label"], "score": g["score"], "quote": (g.get("evidence") or {}).get("quote")} for g in r.get("winners", [])[:3]],
        "share_intent": ((r.get("viral") or {}).get("raw") or {}).get("mean_share_intent"),
    }
    try:
        d = await llm.complete_json(system=OPTIMIZE_SYSTEM, user=json.dumps(evidence, ensure_ascii=False, default=str), role="report",
                                    max_tokens=1600, usage=usage, temperature=0.5)
    except LLMAuthError:
        raise
    except Exception:
        return None
    items = lambda k: [x for x in (d.get(k) or []) if isinstance(x, dict) and x.get("text")][:4]  # noqa: E731
    hook = d.get("hook") if isinstance(d.get("hook"), dict) and d["hook"].get("text") else None
    return {"titles": items("titles"), "hook": hook, "ctas": items("ctas"),
            "edits": [x for x in (d.get("edits") or []) if isinstance(x, dict) and x.get("change")][:5], "model": llm.model_for("report")}


def _tools_text() -> str:
    return "\n".join(f"- {k}: {v}" for k, v in TOOL_SPECS.items())


async def _react(llm: BaseLLM, usage: Usage, tb: Toolbox, system: str, task: str, emit, min_calls: int, max_calls: int) -> tuple[str, list]:
    transcript = task
    used = []
    for step in range(max_calls + 2):
        d = await llm.complete_json(system=system, user=transcript, role="report", max_tokens=2200, usage=usage, temperature=0.3)
        thought = str(d.get("thought") or "")[:600]
        if d.get("final") and (len(used) >= min_calls or step >= max_calls):
            await emit({"step": step, "thought": thought, "final": True})
            return str(d["final"]), used
        tool = str(d.get("tool") or "")
        if not tool or len(used) >= max_calls:
            transcript += "\n\nYou must now write the final section. Reply with {\"thought\": ..., \"final\": ...}."
            continue
        inp = d.get("input") if isinstance(d.get("input"), dict) else {}
        obs = await tb.call(tool, inp)
        used.append({"tool": tool, "input": inp})
        await emit({"step": step, "thought": thought, "tool": tool, "input": inp, "observation": obs[:700]})
        transcript += f"\n\n[step {step}] thought: {thought}\naction: {tool} {json.dumps(inp, ensure_ascii=False)}\nobservation: {obs}"
        if len(used) < min_calls:
            transcript += f"\n(You have used {len(used)} tool(s); use at least {min_calls}.)"
    return "(The analyst could not complete this section.)", used


async def generate(sim_id: str, llm: BaseLLM, usage: Usage) -> Report:
    async with session_scope() as s:
        sim = await s.get(Simulation, sim_id)
        rep = Report(simulation_id=sim_id, status="running", model=llm.model_for("report"))
        s.add(rep)
        await s.flush()
        rep_id = rep.id
    tb = Toolbox(sim, llm, usage)
    await bus.publish(sim_id, "report.started", {"report_id": rep_id})
    overview = await tb.call("simulation_stats", {"section": "overview"})
    if llm.is_dry:
        outline = _dry_outline(sim)
    else:
        try:
            outline = await llm.complete_json(system=OUTLINE_SYSTEM, role="report", max_tokens=1500, usage=usage, temperature=0.3,
                                              user=json.dumps({"question": sim.requirement, "content": sim.card.get("title"),
                                                               "overview": json.loads(overview) if overview.startswith("{") else overview}, ensure_ascii=False))
        except LLMAuthError:
            raise
        except Exception:
            outline = _dry_outline(sim)
    sections_plan = [x for x in outline.get("sections", []) if isinstance(x, dict) and x.get("title")][:5] or _dry_outline(sim)["sections"]
    await bus.publish(sim_id, "report.outline", {"title": outline.get("title"), "summary": outline.get("summary"),
                                                 "sections": [x["title"] for x in sections_plan]})
    sections = []
    system = REACT_SYSTEM.format(tools=_tools_text(), min_calls=2, max_calls=5)
    for i, sec in enumerate(sections_plan):
        async def emit(payload, i=i):
            await bus.publish(sim_id, "report.log", {"section": i, **payload})

        if llm.is_dry:
            content, used = await _dry_section(tb, sec, emit)
        else:
            task = (f"User question: {sim.requirement}\nReport title: {outline.get('title')}\nSection {i + 1}: {sec['title']}\n"
                    f"Goal: {sec.get('goal', '')}\nOverview: {overview}")
            content, used = await _react(llm, usage, tb, system, task, emit, 2, 5)
        sections.append({"title": sec["title"], "content": content, "tools": used})
        await bus.publish(sim_id, "report.section", {"index": i, "title": sec["title"], "content": content})
        async with session_scope() as s:
            r = await s.get(Report, rep_id)
            r.sections = list(sections)
    md = f"# {outline.get('title') or 'Simulation report'}\n\n{outline.get('summary', '')}\n\n" + "\n\n".join(
        f"## {x['title']}\n\n{x['content']}" for x in sections)
    rewrites = await optimize(sim, llm, usage)
    if rewrites:
        async with session_scope() as s:
            row = await s.get(Simulation, sim_id)
            res = copy.deepcopy(row.results or {})
            res["rewrites"] = rewrites
            row.results = res
            flag_modified(row, "results")
        await bus.publish(sim_id, "report.rewrites", rewrites)
    async with session_scope() as s:
        r = await s.get(Report, rep_id)
        r.title, r.summary, r.outline, r.sections, r.markdown, r.status = (outline.get("title") or "Simulation report",
                                                                          outline.get("summary", ""), sections_plan, sections, md, "done")
    return r


async def chat(sim: Simulation, report_md: str, history: list[dict], question: str, llm: BaseLLM, usage: Usage) -> dict:
    tb = Toolbox(sim, llm, usage)
    if llm.is_dry:
        return {"answer": "[dry run] Connect a model in Settings to chat with the ReportAgent. The report above was assembled from the "
                          "simulation statistics by rules.", "tools": []}
    convo = "\n".join(("User: " if h["role"] == "user" else "Analyst: ") + h["content"] for h in history[-10:])
    system = CHAT_SYSTEM.format(tools=_tools_text(), report=report_md[:12000])
    log = []

    async def emit(p):
        log.append(p)
    answer, used = await _react(llm, usage, tb, system, (convo + "\n" if convo else "") + f"User: {question}", emit, 0, 2)
    return {"answer": answer, "tools": used}


# ---- dry run ----------------------------------------------------------------------------------------------
def _dry_outline(sim: Simulation) -> dict:
    sc = (sim.results or {}).get("score", {})
    return {"title": f"[dry run] How audiences responded to “{sim.card.get('title', 'the content')}”",
            "summary": f"[dry run] Projected opinion {sc.get('mean', '?')}/10 after discussion (first impression {sc.get('first_impression', '?')}). "
                       "This report was assembled by rules from the simulation statistics; connect a model for an analyst-written report.",
            "sections": [{"title": "Who it lands with", "goal": "segments"}, {"title": "Where attention drops", "goal": "attention"},
                         {"title": "How the conversation evolved", "goal": "discourse"}, {"title": "How far it spreads", "goal": "spread"}]}


async def _dry_section(tb: Toolbox, sec: dict, emit) -> tuple[str, list]:
    goal = sec.get("goal", "overview")
    calls = [("simulation_stats", {"section": goal}), ("top_posts", {"platform": "any", "limit": 3})]
    used, obs = [], []
    for k, (tool, inp) in enumerate(calls):
        o = await tb.call(tool, inp)
        used.append({"tool": tool, "input": inp})
        obs.append(o)
        await emit({"step": k, "thought": f"[dry run] gather {goal} evidence", "tool": tool, "input": inp, "observation": o[:500]})
    r = tb.r
    lines = []
    if goal == "segments":
        for g in r.get("winners", [])[:2]:
            lines.append(f"- **{g['label']}** score {g['score']:.1f} ({g['share_of_audience']:.1%} of audience)")
        for g in r.get("losers", [])[:2]:
            lines.append(f"- Weakest: **{g['label']}** {g['score']:.1f}")
    elif goal == "attention":
        for s in r.get("heatmap", {}).get("segments", [])[:6]:
            lines.append(f"- Segment {s['i'] + 1}, {s['label']}: holds {s['engagement']:.0%}, {s['retention']:.0%} still watching")
    elif goal == "discourse":
        d = r.get("discourse", {})
        lines.append(f"- {d.get('changed_mind', 0)} interviewed agents moved their score by 1+ point; polarisation "
                     f"{d.get('polarization_before')} → {d.get('polarization_after')}")
        for p in d.get("top_posts", [])[:3]:
            lines.append(f"> {p['content'][:160]} — {p['author']}")
    else:
        c = r.get("viral", {}).get("cascade", {})
        lines.append(f"- Median reach {c.get('reach_median', 0):,} from {c.get('seeds', 0):,} seeds (×{c.get('amplification_median')})")
    await emit({"step": len(calls), "thought": "[dry run] compose", "final": True})
    return "[dry run] Rule-based summary.\n\n" + "\n".join(lines), used
