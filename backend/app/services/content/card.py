"""Content → timed segments → content card. Agents never see raw files; they see the card."""
from __future__ import annotations

import os
import re

import numpy as np

from app.services.llm import BaseLLM, Usage
from app.services.population.regions import INTEREST_LABELS, INTERESTS

from .formats import FORMATS
from .formats import resolve as resolve_format
from .media import (
    ContentError,
    b64file,
    document_text,
    extract_frames,
    has_video_stream,
    looks_like_subtitles,
    parse_subtitles,
    probe_duration,
    transcribe,
)

WPS = 2.5  # spoken words per second


def group_cues(cues: list[dict], duration: float | None = None) -> list[dict]:
    if not cues:
        return []
    total = duration or cues[-1]["end"]
    target = total / int(min(12, max(4, round(total / 6))))
    segs, cur = [], None
    for c in cues:
        if cur is None:
            cur = dict(c)
        else:
            cur["end"] = c["end"]
            cur["text"] += " " + c["text"]
        if cur["end"] - cur["start"] >= target * 0.95:
            segs.append(cur)
            cur = None
    if cur:
        if segs and cur["end"] - cur["start"] < target * 0.4:
            segs[-1]["end"] = cur["end"]
            segs[-1]["text"] += " " + cur["text"]
        else:
            segs.append(cur)
    return segs


def _sentences(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[.!?؟。])\s+|\n{2,}|\n(?=[-•*\d])", text.strip()) if p and p.strip()]


def segment_text(text: str, timed: bool) -> list[dict]:
    sents = _sentences(text)
    if not sents:
        raise ContentError("The content text is empty.")
    words = [len(s.split()) for s in sents]
    total = sum(words)
    n = int(min(12, max(3, round(total / WPS / 6)))) if timed else int(min(10, max(3, round(total / 35))))
    n = min(n, len(sents))
    per = total / n
    segs, buf, wc = [], [], 0
    for s, w in zip(sents, words):
        buf.append(s)
        wc += w
        if wc >= per * 0.95 and len(segs) < n - 1:
            segs.append({"text": " ".join(buf), "words": wc})
            buf, wc = [], 0
    if buf:
        segs.append({"text": " ".join(buf), "words": wc})
    t = 0.0
    for s in segs:
        if timed:
            s["start"] = round(t, 1)
            t += s["words"] / WPS
            s["end"] = round(t, 1)
        s.pop("words", None)
    return segs


def prepare(v: dict, files: dict[str, str], work_dir: str) -> dict:
    """v: content variant {type, format, title, text, transcript, description, asset_id, asset_ids, poll_options};
    files: asset_id -> local path."""
    ctype = v.get("type") or "text"
    text = (v.get("text") or "").strip()
    transcript = (v.get("transcript") or "").strip()
    fpath = files.get(v.get("asset_id") or "")
    out = {"type": ctype, "title": v.get("title") or "", "description": (v.get("description") or "").strip(),
           "segments": [], "duration": None, "images": [], "timed": ctype in ("video", "audio"), "notes": [],
           "poll_options": [o for o in (v.get("poll_options") or []) if o]}
    slides = [files[a] for a in (v.get("asset_ids") or []) if a in files]
    if ctype == "image" and (slides or len(v.get("asset_ids") or []) > 1):
        captions = [x.strip() for x in out["description"].splitlines() if x.strip()]
        n = max(len(slides), len(captions))
        if n == 0:
            raise ContentError("Upload the carousel slides or describe each one on its own line.")
        out["images"] = [b64file(sp) for sp in slides[:10]]
        out["segments"] = [{"text": (captions[k] if k < len(captions) else f"Slide {k + 1}") + (f" — {text}" if k == 0 and text else "")}
                           for k in range(min(n, 10))]
        out["timed"] = False
        return out
    if ctype == "image":
        if fpath:
            out["images"] = [b64file(fpath)]
        if not fpath and not out["description"] and not text:
            raise ContentError("Upload an image or describe it.")
        out["segments"] = [{"text": " ".join(x for x in [text, out["description"]] if x) or "(image only)"}]
        out["timed"] = False
        return out
    if ctype in ("video", "audio"):
        cues = parse_subtitles(transcript) if transcript and looks_like_subtitles(transcript) else []
        if fpath:
            out["duration"] = probe_duration(fpath)
            if not cues and not transcript:
                cues = transcribe(fpath)
                out["notes"].append("Transcribed locally with faster-whisper.")
        if cues:
            out["segments"] = group_cues(cues, out["duration"])
        else:
            script = transcript or text
            if not script:
                raise ContentError("Add a transcript or script for this video/audio.")
            out["segments"] = segment_text(script, timed=True)
            if out["duration"] and out["segments"]:
                k = out["duration"] / max(out["segments"][-1]["end"], 1e-6)
                for s in out["segments"]:
                    s["start"], s["end"] = round(s["start"] * k, 1), round(s["end"] * k, 1)
            out["notes"].append("Segment timings estimated from the script at 2.5 words/second.")
        if not out["duration"] and out["segments"]:
            out["duration"] = out["segments"][-1].get("end")
        if fpath and ctype == "video" and has_video_stream(fpath):
            mids = [(s["start"] + s["end"]) / 2 for s in out["segments"]][:10]
            for s, p in zip(out["segments"], extract_frames(fpath, mids, os.path.join(work_dir, "frames"))):
                s["frame"] = p
        return out
    if not text and fpath:
        with open(fpath, "rb") as fh:
            text = document_text(fh.read(), fpath)
    if not text:
        raise ContentError("Paste the text or upload a document (PDF, Word or text file).")
    if out["poll_options"]:
        opts = "  ".join(f"({k + 1}) {o}" for k, o in enumerate(out["poll_options"]))
        out["segments"] = [{"text": text}, {"text": f"Options: {opts}"}]
    else:
        out["segments"] = segment_text(text, timed=False)
    out["timed"] = False
    return out


# ---- model-free metrics ----------------------------------------------------------------------------
def _syllables(w: str) -> int:
    g = re.findall(r"[aeiouy]+", w.lower())
    return max(1, len(g) - (1 if w.lower().endswith("e") and len(g) > 1 else 0))


def flesch(text: str) -> float | None:
    words = re.findall(r"[A-Za-z']+", text)
    if len(words) < 20:
        return None
    sents = max(1, len(re.findall(r"[.!?]+", text)))
    return round(206.835 - 1.015 * (len(words) / sents) - 84.6 * (sum(_syllables(w) for w in words) / len(words)), 1)


TOPIC_LEXICON = {
    "comedy": "funny joke lol prank comedy meme laugh hilarious skit roast نكتة ضحك مقلب",
    "music": "song music album beat rap singer concert track remix lyrics أغنية موسيقى",
    "gaming": "game gaming gamer fortnite minecraft playstation xbox esports fifa valorant لعبة",
    "tech": "tech phone iphone android app software gadget laptop startup code robot تقنية ذكاء",
    "finance": "money invest stock crypto bitcoin salary budget saving rich price inflation loan مال استثمار",
    "fashion_beauty": "fashion outfit makeup skincare beauty style perfume abaya hair dress موضة مكياج عطر",
    "food": "food recipe cook eat restaurant taste chef dessert coffee shawarma machboos أكل طبخ مطعم",
    "sports": "football soccer match goal team league cricket basketball player coach ronaldo كرة مباراة",
    "news_politics": "government election policy war minister president news law protest crisis سياسة حكومة",
    "religion": "allah ramadan prayer quran mosque faith eid islam god church dua رمضان صلاة",
    "education": "learn study tutorial explain lesson course school university tips guide how تعلم",
    "travel": "travel trip hotel flight beach visit tour city vacation holiday سفر رحلة",
    "cars": "car cars drift engine supercar drive driving bmw toyota patrol lamborghini سيارة",
    "family": "family kids mom dad parent baby child wedding marriage home عائلة أطفال",
    "fitness_health": "gym workout fitness health diet protein run weight muscle sleep doctor squats plank صحة رياضة",
    "film_tv": "movie film series netflix episode actor trailer drama cinema anime مسلسل فيلم",
}


def heuristic_topics(text: str) -> dict:
    t = text.lower()
    scores = {k: sum(len(re.findall(r"\b" + re.escape(w) + r"\w*", t)) for w in ws.split()) for k, ws in TOPIC_LEXICON.items()}
    scores = {k: v for k, v in scores.items() if v}
    if not scores:
        return {"education": 0.3, "comedy": 0.2, "news_politics": 0.2, "tech": 0.3}
    tot = sum(scores.values())
    return {k: round(v / tot, 3) for k, v in sorted(scores.items(), key=lambda x: -x[1])[:4]}


_STOPWORDS = set("""a about above after again against all also am an and any are as at be because been before being below between both
but by can could did do does doing don't down during each even every few for from further get gets got had has have having he her here
hers him his how i if in into is it its itself just keep let like make me more most much must my never no nor not now of off on once
only or other our ours out over own right same she should so some such than that the their them then there these they this those
through to too under until up very was we were what when where which while who whom why will with without would you your yours
yourself first last next really thing things way ways people time times day days new one two three ten twenty don't doesn't isn't
mean means show shows stop starts start want wants need needs come comes going join today tonight""".split())


def heuristic_keywords(text: str, k: int = 8) -> list[str]:
    """Frequency-ranked content words (ties broken by first appearance)."""
    words = re.findall(r"[A-Za-z][A-Za-z'-]{3,}|[؀-ۿ]{3,}", text)
    counts: dict[str, int] = {}
    for w in words:
        lw = w.lower().strip("'-")
        if lw not in _STOPWORDS and len(lw) >= 4:
            counts[lw] = counts.get(lw, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda x: -x[1])][:k]


def heuristic_entities(text: str, k: int = 12) -> list[str]:
    """Proper-noun phrases. A capitalised word at the start of a sentence only counts when it is part of a
    multi-word name or is also capitalised mid-sentence somewhere else, so "Hydrate between…" is not a name."""
    found: dict[str, int] = {}
    mid_caps: set[str] = set()
    for sent in re.split(r"(?<=[.!?:])\s+|\n+", text):
        for m in re.finditer(r"\b[A-Z][A-Za-z]+(?:\s(?:[A-Z][A-Za-z]+|of|al|el|bin))*(?:\s[A-Z][A-Za-z]+)?", sent):
            phrase = m.group(0).strip()
            if m.start() > 0:
                mid_caps.update(phrase.split())
            found.setdefault(phrase, m.start())
    out = []
    for phrase, pos in found.items():
        words = phrase.split()
        if phrase.lower() in _STOPWORDS or len(phrase) < 3:
            continue
        if pos == 0 and len(words) == 1 and phrase not in mid_caps:
            continue
        if pos == 0 and len(words) > 1 and words[0].lower() in _STOPWORDS:
            phrase = " ".join(words[1:])
        out.append(phrase)
    return list(dict.fromkeys(out))[:k]


def heuristic_hook(first: str) -> float:
    f = first.strip().lower()
    s = 0.35 + (0.12 if re.search(r"[?؟]", f) else 0) + (0.08 if re.search(r"\d", f) else 0)
    s += 0.08 if re.search(r"\b(you|your|انت|أنت)\b", f) else 0
    s += 0.1 if len(f.split()) <= 18 else 0
    s += 0.1 if re.search(r"\b(secret|never|stop|why|how|worst|best|mistake|truth)\b", f) else 0
    return round(min(0.9, s), 2)


def topic_vector(topics: dict) -> np.ndarray:
    v = np.zeros(len(INTERESTS), dtype=np.float32)
    for k, w in (topics or {}).items():
        if k in INTERESTS:
            try:
                v[INTERESTS.index(k)] = max(0.0, float(w))
            except (TypeError, ValueError):
                pass
    if v.sum() <= 0:
        v[:] = 1.0
    return v / v.sum()


def fmt_t(t) -> str:
    if t is None:
        return "?"
    return f"{int(float(t) // 60)}:{int(float(t) % 60):02d}"


def _label(text: str) -> str:
    w = re.findall(r"[\w؀-ۿ']+", text)
    return " ".join(w[:4]) + ("…" if len(w) > 4 else "")


CARD_SYSTEM = """You analyse a piece of social content before it is shown to a simulated audience.
Be concrete and literal. Describe what is there; do not praise or critique.

Return JSON:
{"summary": "2 sentences: what the content is and what it asks of the viewer",
 "format": "e.g. talking-head explainer, skit, product ad, carousel, news clip, essay",
 "language": "main language/dialect", "tone": "e.g. earnest, ironic, urgent, playful",
 "topics": {"<topic key>": weight 0-1, ... up to 4 keys from the allowed list},
 "keywords": ["5-10 specific keywords"], "entities": ["people, brands, places, events named"],
 "hook": {"strength": 0-1, "why": "one sentence about the first seconds/lines"},
 "segment_labels": ["2-5 word label per segment, same order and count"],
 "segment_notes": ["one short factual note per segment"],
 "cta": "call to action or empty", "claims": ["claims a skeptic might challenge"],
 "sensitivity_flags": ["specific cultural, religious, political or age-appropriateness risks, especially for Gulf/MENA audiences"]}
Allowed topic keys: """ + ", ".join(INTERESTS)


async def build_card(prep: dict, meta: dict, llm: BaseLLM, usage: Usage) -> dict:
    segs = prep["segments"]
    full = " ".join(s["text"] for s in segs)
    fmt_key = resolve_format(meta.get("format"), prep["type"])
    opening = (segs[0]["text"] if segs else "").strip()
    fallback = (opening[:70].rsplit(" ", 1)[0] + "…") if len(opening) > 70 else (opening or "Untitled")
    card = {"title": prep["title"] or meta.get("title") or fallback, "type": prep["type"], "platform": meta.get("platform"),
            "format_key": fmt_key, "format_label": FORMATS[fmt_key]["label"], "format_lens": FORMATS[fmt_key]["lens"],
            "poll_options": prep.get("poll_options") or [],
            "goal": meta.get("goal") or "", "duration": prep["duration"], "timed": prep["timed"], "description": prep["description"],
            "notes": list(prep["notes"]), "readability": flesch(full), "word_count": len(full.split()),
            "segments": [{"i": i, "start": s.get("start"), "end": s.get("end"), "text": s["text"], "has_frame": bool(s.get("frame"))}
                         for i, s in enumerate(segs)]}
    images = list(prep["images"])
    frames = [s["frame"] for s in segs if s.get("frame")][:8]
    if llm.has_vision() and frames:
        images += [b64file(p) for p in frames]
    if not llm.has_vision() and (images or frames):
        card["notes"].append("No vision model configured: visuals were not analysed.")
        images = []
    if llm.is_dry:
        for s in card["segments"]:
            s["label"], s["note"] = _label(s["text"]), ""
        arabic = len(re.findall(r"[؀-ۿ]", full)) > len(full) * 0.3
        card.update({"summary": f"[dry run] {full[:220]}{'…' if len(full) > 220 else ''}", "format": "unknown (dry run)",
                     "language": "Arabic" if arabic else "English", "tone": "unknown (dry run)",
                     "topics": heuristic_topics(full + " " + card["title"]),
                     "keywords": heuristic_keywords(full),
                     "entities": heuristic_entities(card["title"] + ". " + full, 10),
                     "hook": {"strength": heuristic_hook(segs[0]["text"] if segs else ""), "why": "[dry run] rule-based"},
                     "cta": "", "claims": [], "sensitivity_flags": [], "analysed_by": "dry-run heuristics"})
    else:
        lines = [f"[{i + 1}] " + (f"{fmt_t(s.get('start'))}-{fmt_t(s.get('end'))} " if prep["timed"] else "") + s["text"][:900]
                 for i, s in enumerate(segs)]
        user = (f"Title: {card['title']}\nType: {card['type']}\nTarget platform: {meta.get('platform')}\nCreator goal: {meta.get('goal') or '-'}\n"
                f"Creator's description: {prep['description'] or '-'}\n"
                + (f"Images attached: {len(images)}\n" if images else "") + "\nSegments:\n" + "\n".join(lines))
        d = await llm.complete_json(system=CARD_SYSTEM, user=user, role="content", max_tokens=2500, usage=usage,
                                    images=images or None, temperature=0.2)
        num = lambda v, dflt: max(0.0, min(1.0, float(v))) if _isnum(v) else dflt  # noqa: E731
        card.update({"summary": str(d.get("summary") or ""), "format": str(d.get("format") or ""), "language": str(d.get("language") or ""),
                     "tone": str(d.get("tone") or ""),
                     "topics": {k: float(v) for k, v in (d.get("topics") or {}).items() if k in INTERESTS and _isnum(v)},
                     "keywords": [str(x) for x in (d.get("keywords") or [])][:12], "entities": [str(x) for x in (d.get("entities") or [])][:15],
                     "hook": {"strength": num((d.get("hook") or {}).get("strength"), 0.5), "why": str((d.get("hook") or {}).get("why") or "")},
                     "cta": str(d.get("cta") or ""), "claims": [str(x) for x in (d.get("claims") or [])][:8],
                     "sensitivity_flags": [str(x) for x in (d.get("sensitivity_flags") or [])][:8],
                     "analysed_by": llm.model_for("vision" if images else "content")})
        labels, notes = d.get("segment_labels") or [], d.get("segment_notes") or []
        for i, s in enumerate(card["segments"]):
            s["label"] = str(labels[i]) if i < len(labels) else _label(s["text"])
            s["note"] = str(notes[i]) if i < len(notes) else ""
    if not card.get("topics"):
        card["topics"] = heuristic_topics(full + " " + card["title"])
    card["topic_labels"] = {k: INTEREST_LABELS[k] for k in card["topics"]}
    return card


def _isnum(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def card_block(card: dict) -> str:
    lines = [f"Title: {card['title']}", f"Format: {card.get('format_label') or card['type']}" + (f" ({card['format']})" if card.get("format") else "")]
    if card.get("format_lens"):
        lines.append(f"How people encounter it: {card['format_lens']}")
    if card.get("poll_options"):
        lines.append("Poll options: " + "  ".join(f"({k + 1}) {o}" for k, o in enumerate(card["poll_options"])))
    if card.get("duration"):
        lines.append(f"Length: {fmt_t(card['duration'])}")
    for k, label in (("summary", "Summary"), ("language", "Language"), ("tone", "Tone"), ("cta", "Call to action")):
        if card.get(k):
            lines.append(f"{label}: {card[k]}")
    if card.get("entities"):
        lines.append("Mentions: " + ", ".join(card["entities"][:10]))
    if card.get("description"):
        lines.append(f"Visual description from creator: {card['description'][:600]}")
    lines += ["", "SEGMENTS (in order):"]
    for s in card["segments"]:
        tl = f"{fmt_t(s['start'])}-{fmt_t(s['end'])} " if card.get("timed") else ""
        note = f" [{s['note']}]" if s.get("note") else ""
        lines.append(f"[{s['i'] + 1}] {tl}{s.get('label', '')}{note}: {s['text'][:700]}")
    return "\n".join(lines)
