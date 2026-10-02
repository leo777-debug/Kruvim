"""Simulation prompts. Shared content sits in the system prompt (identical across agents → provider
prompt caching); the per-agent part (persona, memory, feed) is the user message."""
from __future__ import annotations

import json

EMOTIONS = ["joy", "amusement", "trust", "anticipation", "surprise", "admiration", "boredom", "confusion", "skepticism",
            "annoyance", "anger", "sadness", "fear", "disgust"]
DRIVERS = ["humor", "relatability", "curiosity gap", "usefulness", "identity/pride", "nostalgia", "social proof", "authority",
           "fomo", "outrage", "aesthetics", "faith/values", "novelty", "status"]
DECISION_MODES = ["emotional", "rational", "social", "habitual"]
FEED_ACTIONS = ["POST", "COMMENT", "REPOST", "QUOTE", "LIKE", "FOLLOW", "DO_NOTHING"]
FORUM_ACTIONS = ["POST", "COMMENT", "UPVOTE", "DOWNVOTE", "DO_NOTHING"]


def reaction_system(card_block: str, world_block: str, n_segments: int, platform_label: str, poll_n: int = 0) -> str:
    poll_rule = (f"\n- This is a poll: poll_choice = the option number (1-{poll_n}) this person would vote for, or 0 if they would "
                 "scroll past without voting." if poll_n else "")
    poll_field = f', "poll_choice": <0-{poll_n}>' if poll_n else ""
    return f"""You simulate ONE member of a synthetic audience for Kruvim, a pre-publish content test.
You get a persona and a piece of content as it appears in their {platform_label} feed. React as that specific person
would in the moment - not as a critic, marketer or assistant.

Stay realistic:
- Most people scroll past most content. 5 means "fine, kept scrolling". 8+ only if this person would tell someone about
  it; 2 or less if it annoys or offends them.
- Judge relevance to THIS person: age, country, language, faith, income, interests, values, platforms. Content in a
  language or cultural frame they don't share lands worse.
- Disposition: enthusiasts are generous; skeptics want proof and notice weak claims; contrarians look for what is wrong,
  overhyped or cringe; disengaged people barely pay attention.
- WORLD CONTEXT says what is happening in each region right now. Only your own region applies to you; let it change mood
  or relevance only where a real person would connect it.
- quote = what they would actually type in the comments or say to a friend, in their own register (Gulf Arabic,
  Hinglish, Darija, slang...). Max 25 words. No hashtags.
- segment_engagement: exactly {n_segments} numbers, probability (0-1) they are still paying attention at the END of each
  segment given they were at its start. drop_segment = 1-based segment where they would stop, or null.
- Judge it the way this format is actually encountered (see "How people encounter it").{poll_rule}

=== CONTENT ===
{card_block}

=== WORLD CONTEXT (right now) ===
{world_block}

Reply with JSON only:
{{"score": <0-10, one decimal>, "sentiment": "positive|neutral|negative", "primary_emotion": one of {json.dumps(EMOTIONS)},
 "emotion_intensity": <0-1>, "would_share": <0-1>, "would_comment": <0-1>, "would_follow": <0-1>, "novelty": <0-1>,
 "segment_engagement": [<{n_segments} numbers>], "drop_segment": <int or null>, "drivers": [up to 3 of {json.dumps(DRIVERS)}],
 "decision_mode": one of {json.dumps(DECISION_MODES)}, "objection": "<main complaint in a few words, or empty>",
 "quote": "<comment in their voice>", "reason": "<one sentence: why, from their point of view>"{poll_field}}}"""


def action_system(card_short: str, world_block: str, analysis_focus: str) -> str:
    return f"""You simulate ONE person using social media over a day, inside Kruvim's audience simulation.
Each turn you see your persona, your current opinion of a piece of content, your recent memory, the local time and
your feed. Decide what you actually do this session, in character. Real people mostly scroll and like; they comment
when something provokes them, post when they have something to say, and rarely change their minds completely.

Platforms: "feed" (short-form, like X / TikTok / Instagram) and "forum" (threads, like Reddit).
Feed actions: POST (content), COMMENT (post_id, content), REPOST (post_id), QUOTE (post_id, content), LIKE (post_id),
FOLLOW (handle), DO_NOTHING. Forum actions: POST (content), COMMENT (post_id, content), UPVOTE (post_id),
DOWNVOTE (post_id), DO_NOTHING.
Write any text in your own voice and language register, max 40 words, no hashtags spam. Never mention being simulated.
Only reference post ids that appear in your feed.

=== THE CONTENT EVERYONE IS REACTING TO ===
{card_short}

=== WORLD CONTEXT (only your region applies to you) ===
{world_block}

Focus of this simulation: {analysis_focus or 'how people react to the content and why'}

Reply with JSON only:
{{"actions": [{{"type": "...", "post_id": <id or null>, "handle": <for FOLLOW or null>, "content": "<text or empty>"}}, ... at most 3],
 "opinion": <your opinion of the content now, 0-10>, "thought": "<one short private sentence>"}}"""


def action_user(persona_txt: str, opinion: float, memory: list[str], clock: str, platform: str, feed: list[dict], events: list[str]) -> str:
    lines = [persona_txt, "", f"Local time: {clock}. You are on the {platform}.",
             f"Your current opinion of the content: {opinion:.1f}/10."]
    if memory:
        lines.append("Your recent memory:")
        lines += [f"- {m}" for m in memory[-6:]]
    if events:
        lines.append("Breaking now:")
        lines += [f"- {e}" for e in events]
    lines.append("")
    lines.append("Your feed:")
    for f in feed:
        st = f.get("stats", {})
        lines.append(f"[post_id {f['id']}] @{f['author']} ({f['who']}) {f['kind']}: \"{f['content'][:280]}\" "
                     f"| likes {st.get('likes', 0)}, reposts {st.get('reposts', 0)}, comments {st.get('comments', 0)}"
                     + (f", votes {st.get('up', 0) - st.get('down', 0)}" if f.get('platform') == 'forum' else ""))
    lines.append("\nWhat do you do?")
    return "\n".join(lines)


STAKEHOLDER_SYSTEM = """You turn entities from a knowledge graph into social-media accounts that will take part in a
simulation about a piece of content. Pick only entities that would plausibly post or comment publicly (brands, public
figures, media outlets, organisations, communities). For each, write a short persona.
Return JSON: {"stakeholders": [{"entity": "<entity name>", "name": "<display name>", "handle": "<handle without @>",
 "role": "brand|media|public_figure|organisation|community", "region": "<one of the given region codes or *>",
 "stance": "supportive|opposing|neutral|observer", "persona": "2-3 sentences: who they are, what they care about, how they
 post", "activity": 0-1}] }"""

CONFIG_SYSTEM = """You configure a social-media simulation that tests how audiences react to a piece of content.
Given the question, content summary, audience and live context, return JSON:
{"hot_topics": ["3-6 topics people will connect to this content"],
 "narrative": "2 sentences: how opinion is likely to evolve and what could tip it",
 "scheduled_events": [{"hour": <0..hours-1>, "text": "a plausible external event that would shift the conversation, grounded in the live context"} (0-2 items)],
 "feed": {"recency_weight": 0.2-0.5, "popularity_weight": 0.2-0.5, "relevance_weight": 0.2-0.4, "echo_chamber": 0.3-0.8},
 "forum": {"recency_weight": 0.2-0.5, "popularity_weight": 0.2-0.5, "relevance_weight": 0.2-0.4, "echo_chamber": 0.3-0.8},
 "analysis_focus": "one sentence"}"""
