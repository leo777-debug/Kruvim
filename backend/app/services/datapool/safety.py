"""Conservative discovery-feed filter, separate from user-supplied research content."""
import re

_ADULT = re.compile(r"porn|xxx|hentai|onlyfans|sex(?:ual|_act|_position| work)|erotic|masturbat|fetish|prostitut|"
                    r"adult[ _-](?:film|entertain|content)|إباح|اباح|جنس|دعارة|عري|pornograph|sexualité", re.I)


def safe_title(title, categories=()):
    return not _ADULT.search(str(title).replace("_", " ")) and not any(_ADULT.search(str(c)) for c in categories)


def clean_snapshot(data):
    out = dict(data)
    for key in ("signals", "news", "trending", "social", "trend_series"):
        out[key] = [x for x in out.get(key, []) if safe_title(x.get("title", ""))]
    return out
