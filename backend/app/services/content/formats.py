"""Content formats a creator can test. Each maps onto one of four processing types (video, audio, image, text) and
tells the agents how people actually encounter that kind of content, which changes how they judge it."""
from __future__ import annotations

FORMATS: dict[str, dict] = {
    "short_video": {"label": "Short video", "hint": "Reel, TikTok, YouTube Short", "type": "video", "platform": "tiktok", "group": "Video",
                    "lens": "a short vertical video in a fast-scrolling feed; most people decide within the first two seconds whether to keep watching"},
    "long_video": {"label": "Long-form video", "hint": "YouTube video, vlog, documentary, webinar", "type": "video", "platform": "youtube", "group": "Video",
                   "lens": "a long video they chose to open; they give it some patience at the start but leave as soon as it drags"},
    "video_ad": {"label": "Video ad", "hint": "Sponsored post, pre-roll, TV or OOH spot", "type": "video", "platform": "instagram", "group": "Video",
                 "lens": "a paid advertisement shown between other content; they know it is selling something and skip unless it earns attention"},
    "podcast": {"label": "Podcast", "hint": "Episode or clip", "type": "audio", "platform": "youtube", "group": "Audio",
                "lens": "a podcast they listen to while doing something else; voice, pace and whether the topic holds them matter most"},
    "song": {"label": "Song or music", "hint": "Track, jingle, trending sound", "type": "audio", "platform": "tiktok", "group": "Audio",
             "lens": "music: judge catchiness, replay value, whether they would save it or use it as a sound, and whether the lyrics fit their values"},
    "thumbnail": {"label": "Thumbnail and title", "hint": "Click test for a YouTube video", "type": "image", "platform": "youtube", "group": "Image",
                  "lens": "only a thumbnail and title among other recommended videos; the score is how likely they are to click it"},
    "image_post": {"label": "Image post", "hint": "Photo, meme, poster, infographic", "type": "image", "platform": "instagram", "group": "Image",
                   "lens": "a single image in their feed, seen for a second or two unless it stops them"},
    "carousel": {"label": "Carousel", "hint": "2 to 10 slides", "type": "image", "platform": "instagram", "group": "Image", "multi": True,
                 "lens": "a swipeable carousel; the first slide decides whether they swipe, each later slide whether they keep going"},
    "social_post": {"label": "Text post", "hint": "Tweet, thread, caption, LinkedIn post", "type": "text", "platform": "x", "group": "Text",
                    "lens": "a text post in their feed; they read the first line and continue only if it is worth it"},
    "article": {"label": "Article", "hint": "Blog post, newsletter, press release", "type": "text", "platform": "linkedin", "group": "Text",
                "lens": "an article they clicked into; they skim headings and leave when it stops paying off"},
    "poll": {"label": "Poll", "hint": "Question with 2 to 6 options", "type": "text", "platform": "x", "group": "Text", "poll": True,
             "lens": "a poll in their feed; they decide whether to vote and which option to pick"},
    "study_material": {"label": "Study material", "hint": "Lesson, course notes, exam prep", "type": "text", "platform": "youtube", "group": "Document",
                       "lens": "study material a learner works through; they judge clarity, whether it holds their attention and whether they learn something they can use"},
    "business_doc": {"label": "Business document", "hint": "Pitch, proposal, review, investor update", "type": "text", "platform": "linkedin", "group": "Document",
                     "lens": "a business document read by professionals; they judge clarity, credibility and whether the argument convinces them"},
    "product_page": {"label": "Product or landing page", "hint": "Product description, launch page, store listing", "type": "text", "platform": "instagram",
                     "group": "Document", "lens": "a product page they arrived at; they decide whether they want it, trust it and would buy or sign up"},
    "tech_doc": {"label": "Technical write-up", "hint": "Code explanation, docs, changelog, RFC", "type": "text", "platform": "linkedin", "group": "Document",
                 "lens": "technical writing; readers judge whether it is accurate, clear and solves their problem, and switch off at jargon they don't need"},
    "market_note": {"label": "Market commentary", "hint": "Trading idea, market update, financial newsletter", "type": "text", "platform": "x", "group": "Document",
                    "lens": "market or trading commentary; readers judge credibility and risk and whether it changes what they would do (audience research, not financial advice)"},
    "scenario": {"label": "Scenario or decision", "hint": "Announcement, price change, policy, plan to test", "type": "text", "platform": "x", "group": "Document",
                 "lens": "an announcement or decision that affects them; they judge fairness, how it changes things for them and how they would respond"},
}

DEFAULT_FOR_TYPE = {"video": "short_video", "audio": "podcast", "image": "image_post", "text": "social_post"}


def resolve(fmt: str | None, ctype: str | None) -> str:
    if fmt in FORMATS:
        return fmt
    return DEFAULT_FOR_TYPE.get(ctype or "text", "social_post")


def public() -> list[dict]:
    return [{"key": k, **{f: v for f, v in d.items() if f != "lens"}} for k, d in FORMATS.items()]
