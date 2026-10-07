"""Region definitions: demographic priors, local clocks, data-pool source mappings.

All demographic numbers are APPROXIMATE PRIORS that make the system run out of the box. Replace them
by importing real survey data (Data Pool → Barometers): Arab Barometer, Pew Global Attitudes,
World Values Survey or census tables. Imported marginals override these per region.

`weight` is the share of Kruvim's synthetic population assigned to a region (a product decision,
MENA-first), not a share of world population. Legacy reach-scale constants are UNSOURCED placeholder
configuration; they are not attributed to DataReportal. Their outputs must carry estimate, source pending.
"""
from __future__ import annotations

from .uae import NATIONALITIES, PLACEHOLDER_ID

AGE_BANDS = [(16, 24), (25, 34), (35, 44), (45, 54), (55, 70)]
AGE_BAND_LABELS = ["16-24", "25-34", "35-44", "45-54", "55-70"]

PLATFORMS = ["tiktok", "instagram", "youtube", "x", "facebook", "snapchat", "linkedin", "reddit"]
PLATFORM_LABELS = {"tiktok": "TikTok", "instagram": "Instagram", "youtube": "YouTube", "x": "X", "facebook": "Facebook",
                   "snapchat": "Snapchat", "linkedin": "LinkedIn", "reddit": "Reddit"}

INTERESTS = ["comedy", "music", "gaming", "tech", "finance", "fashion_beauty", "food", "sports", "news_politics",
             "religion", "education", "travel", "cars", "family", "fitness_health", "film_tv"]
INTEREST_LABELS = {"comedy": "Comedy", "music": "Music", "gaming": "Gaming", "tech": "Tech", "finance": "Money & finance",
                   "fashion_beauty": "Fashion & beauty", "food": "Food", "sports": "Sports", "news_politics": "News & politics",
                   "religion": "Religion & faith", "education": "Learning", "travel": "Travel", "cars": "Cars",
                   "family": "Family & parenting", "fitness_health": "Fitness & health", "film_tv": "Film & TV"}

STANCES = ["enthusiast", "neutral", "skeptic", "contrarian", "disengaged"]
GENDERS = ["female", "male"]
EDUCATION = ["secondary or less", "diploma", "bachelor's", "postgraduate"]
PROFESSIONS = ["student", "unemployed", "service worker", "skilled trade", "office worker", "professional", "manager",
               "self-employed", "homemaker", "retired", "content creator"]
INCOME_LABELS = ["low", "lower-middle", "middle", "upper-middle", "high"]
ATTITUDES = ["religiosity", "media_trust", "political_interest"]

# Hourly activity multipliers (local time, 0..23). Gulf evenings peak late; West peaks 19-22.
GULF_CURVE = [0.55, 0.40, 0.25, 0.12, 0.08, 0.10, 0.20, 0.35, 0.45, 0.50, 0.55, 0.60, 0.65, 0.60, 0.65, 0.75,
              0.85, 0.95, 1.05, 1.15, 1.30, 1.40, 1.35, 0.95]
LEVANT_CURVE = [0.45, 0.30, 0.18, 0.10, 0.07, 0.10, 0.25, 0.45, 0.55, 0.60, 0.62, 0.65, 0.70, 0.70, 0.72, 0.78,
                0.85, 0.95, 1.10, 1.25, 1.35, 1.30, 1.10, 0.75]
WEST_CURVE = [0.30, 0.18, 0.10, 0.06, 0.05, 0.08, 0.25, 0.55, 0.75, 0.80, 0.80, 0.85, 0.95, 0.90, 0.85, 0.85,
              0.90, 1.00, 1.15, 1.30, 1.40, 1.30, 0.95, 0.55]

REGIONS = [
    {"code": "AE", "social_users_m": 10.7, "name": "United Arab Emirates", "short": "UAE", "city": "Dubai", "lat": 25.2048, "lon": 55.2708,
     "tz_offset": 4.0, "curve": GULF_CURVE, "weight": 0.18, "male_share": 0.69, "citizen_share": 0.12,
     "citizen_label": "Emirati", "expat_labels": ["South Asian expat", "Arab expat", "Filipino expat", "Western expat"],
     "expat_mix": [0.58, 0.20, 0.14, 0.08], "age_bands": [0.14, 0.33, 0.29, 0.15, 0.09], "education": [0.30, 0.22, 0.36, 0.12],
     "languages": ["Arabic (Gulf)", "English", "Hindi/Urdu"], "attitudes": {"religiosity": 0.62, "media_trust": 0.58, "political_interest": 0.35},
     "platforms": {"tiktok": 0.62, "instagram": 0.78, "youtube": 0.85, "x": 0.35, "facebook": 0.55, "snapchat": 0.55, "linkedin": 0.40, "reddit": 0.12},
     "news_rss": "https://news.google.com/rss?hl=ar&gl=AE&ceid=AE:ar", "gdelt_country": "unitedarabemirates", "wiki_lang": "ar",
     "holiday_cc": "AE", "subreddits": ["dubai", "UAE", "abudhabi"], "yt_region": "AE", "lang_code": "ar"},
    {"code": "SA", "social_users_m": 35.1, "name": "Saudi Arabia", "short": "KSA", "city": "Riyadh", "lat": 24.7136, "lon": 46.6753,
     "tz_offset": 3.0, "curve": GULF_CURVE, "weight": 0.18, "male_share": 0.58, "citizen_share": 0.58,
     "citizen_label": "Saudi", "expat_labels": ["South Asian expat", "Arab expat", "Other expat"], "expat_mix": [0.55, 0.30, 0.15],
     "age_bands": [0.20, 0.27, 0.24, 0.16, 0.13], "education": [0.38, 0.17, 0.36, 0.09],
     "languages": ["Arabic (Najdi/Hejazi)", "English"], "attitudes": {"religiosity": 0.72, "media_trust": 0.60, "political_interest": 0.30},
     "platforms": {"tiktok": 0.66, "instagram": 0.62, "youtube": 0.80, "x": 0.55, "facebook": 0.30, "snapchat": 0.78, "linkedin": 0.22, "reddit": 0.06},
     "news_rss": "https://news.google.com/rss?hl=ar&gl=SA&ceid=SA:ar", "gdelt_country": "saudiarabia", "wiki_lang": "ar",
     "holiday_cc": "SA", "subreddits": ["saudiarabia", "riyadh"], "yt_region": "SA", "lang_code": "ar"},
    {"code": "EG", "social_users_m": 46.3, "name": "Egypt", "short": "Egypt", "city": "Cairo", "lat": 30.0444, "lon": 31.2357,
     "tz_offset": 3.0, "curve": LEVANT_CURVE, "weight": 0.16, "male_share": 0.51, "citizen_share": 1.0,
     "citizen_label": "Egyptian", "expat_labels": [], "expat_mix": [], "age_bands": [0.25, 0.24, 0.20, 0.15, 0.16],
     "education": [0.55, 0.15, 0.26, 0.04], "languages": ["Arabic (Egyptian)"],
     "attitudes": {"religiosity": 0.70, "media_trust": 0.40, "political_interest": 0.38},
     "platforms": {"tiktok": 0.48, "instagram": 0.40, "youtube": 0.72, "x": 0.12, "facebook": 0.80, "snapchat": 0.10, "linkedin": 0.08, "reddit": 0.05},
     "news_rss": "https://news.google.com/rss?hl=ar&gl=EG&ceid=EG:ar", "gdelt_country": "egypt", "wiki_lang": "ar",
     "holiday_cc": "EG", "subreddits": ["Egypt", "cairo"], "yt_region": "EG", "lang_code": "ar"},
    {"code": "JO", "social_users_m": 6.5, "name": "Jordan", "short": "Jordan", "city": "Amman", "lat": 31.9539, "lon": 35.9106,
     "tz_offset": 3.0, "curve": LEVANT_CURVE, "weight": 0.06, "male_share": 0.52, "citizen_share": 0.70,
     "citizen_label": "Jordanian", "expat_labels": ["Syrian", "Other"], "expat_mix": [0.7, 0.3],
     "age_bands": [0.26, 0.24, 0.20, 0.15, 0.15], "education": [0.47, 0.16, 0.31, 0.06], "languages": ["Arabic (Levantine)"],
     "attitudes": {"religiosity": 0.65, "media_trust": 0.38, "political_interest": 0.40},
     "platforms": {"tiktok": 0.52, "instagram": 0.55, "youtube": 0.74, "x": 0.15, "facebook": 0.78, "snapchat": 0.25, "linkedin": 0.14, "reddit": 0.06},
     "news_rss": "https://news.google.com/rss/search?q=%D8%A7%D9%84%D8%A3%D8%B1%D8%AF%D9%86&hl=ar&gl=EG&ceid=EG:ar",
     "gdelt_country": "jordan", "wiki_lang": "ar", "holiday_cc": "JO", "subreddits": ["jordan", "amman"], "yt_region": "JO", "lang_code": "ar"},
    {"code": "MA", "social_users_m": 22.2, "name": "Morocco", "short": "Morocco", "city": "Casablanca", "lat": 33.5731, "lon": -7.5898,
     "tz_offset": 1.0, "curve": LEVANT_CURVE, "weight": 0.08, "male_share": 0.50, "citizen_share": 1.0,
     "citizen_label": "Moroccan", "expat_labels": [], "expat_mix": [], "age_bands": [0.21, 0.21, 0.20, 0.17, 0.21],
     "education": [0.62, 0.14, 0.19, 0.05], "languages": ["Arabic (Darija)", "French", "Amazigh"],
     "attitudes": {"religiosity": 0.66, "media_trust": 0.35, "political_interest": 0.28},
     "platforms": {"tiktok": 0.50, "instagram": 0.48, "youtube": 0.75, "x": 0.08, "facebook": 0.70, "snapchat": 0.12, "linkedin": 0.10, "reddit": 0.04},
     "news_rss": "https://news.google.com/rss/search?q=Maroc&hl=fr&gl=FR&ceid=FR:fr", "gdelt_country": "morocco",
     "wiki_lang": "fr", "holiday_cc": "MA", "subreddits": ["Morocco"], "yt_region": "MA", "lang_code": "fr"},
    {"code": "US", "social_users_m": 253, "name": "United States", "short": "USA", "city": "New York", "lat": 40.7128, "lon": -74.0060,
     "tz_offset": -4.0, "curve": WEST_CURVE, "weight": 0.16, "male_share": 0.49, "citizen_share": 1.0,
     "citizen_label": "American", "expat_labels": [], "expat_mix": [], "age_bands": [0.16, 0.19, 0.18, 0.17, 0.30],
     "education": [0.38, 0.10, 0.33, 0.19], "languages": ["English", "Spanish"],
     "attitudes": {"religiosity": 0.45, "media_trust": 0.32, "political_interest": 0.55},
     "platforms": {"tiktok": 0.45, "instagram": 0.55, "youtube": 0.83, "x": 0.22, "facebook": 0.66, "snapchat": 0.28, "linkedin": 0.30, "reddit": 0.25},
     "news_rss": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en", "gdelt_country": "unitedstates", "wiki_lang": "en",
     "holiday_cc": "US", "subreddits": ["news", "AskAnAmerican"], "yt_region": "US", "lang_code": "en"},
    {"code": "GB", "social_users_m": 54.8, "name": "United Kingdom", "short": "UK", "city": "London", "lat": 51.5072, "lon": -0.1276,
     "tz_offset": 1.0, "curve": WEST_CURVE, "weight": 0.08, "male_share": 0.49, "citizen_share": 1.0,
     "citizen_label": "British", "expat_labels": [], "expat_mix": [], "age_bands": [0.14, 0.18, 0.18, 0.18, 0.32],
     "education": [0.40, 0.14, 0.30, 0.16], "languages": ["English"],
     "attitudes": {"religiosity": 0.25, "media_trust": 0.36, "political_interest": 0.50},
     "platforms": {"tiktok": 0.42, "instagram": 0.52, "youtube": 0.80, "x": 0.20, "facebook": 0.62, "snapchat": 0.25, "linkedin": 0.28, "reddit": 0.18},
     "news_rss": "https://news.google.com/rss?hl=en-GB&gl=GB&ceid=GB:en", "gdelt_country": "unitedkingdom", "wiki_lang": "en",
     "holiday_cc": "GB", "subreddits": ["unitedkingdom", "london"], "yt_region": "GB", "lang_code": "en"},
    {"code": "IN", "social_users_m": 491, "name": "India", "short": "India", "city": "Mumbai", "lat": 19.0760, "lon": 72.8777,
     "tz_offset": 5.5, "curve": WEST_CURVE, "weight": 0.10, "male_share": 0.52, "citizen_share": 1.0,
     "citizen_label": "Indian", "expat_labels": [], "expat_mix": [], "age_bands": [0.24, 0.25, 0.21, 0.15, 0.15],
     "education": [0.58, 0.10, 0.25, 0.07], "languages": ["Hindi", "English", "Marathi"],
     "attitudes": {"religiosity": 0.70, "media_trust": 0.50, "political_interest": 0.45},
     "platforms": {"tiktok": 0.0, "instagram": 0.62, "youtube": 0.85, "x": 0.15, "facebook": 0.45, "snapchat": 0.20, "linkedin": 0.18, "reddit": 0.08},
     "news_rss": "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en", "gdelt_country": "india", "wiki_lang": "hi",
     "holiday_cc": "IN", "subreddits": ["india", "mumbai"], "yt_region": "IN", "lang_code": "hi"},
]

# Model configuration, never demographic observations. Native approved cells are fitted at rebuild.
REGIONS[0]["expat_labels"] = NATIONALITIES[1:]
REGIONS[0]["expat_mix"] = [1] * (len(NATIONALITIES) - 1)
for _region in REGIONS:
    _region["population_status"] = "placeholder"
    _region["population_label"] = "estimate, source pending"
    _region["source_ids"] = [PLACEHOLDER_ID]

REGION_CODES = [r["code"] for r in REGIONS]
REGION_INDEX = {r["code"]: i for i, r in enumerate(REGIONS)}
EMIRATE_CONTEXT = [
    {**REGIONS[0], "code": "AE-DXB", "country": "AE", "name": "Dubai", "short": "Dubai", "city": "Dubai", "lat": 25.07725, "lon": 55.30927},
    {**REGIONS[0], "code": "AE-AUH", "country": "AE", "name": "Abu Dhabi", "short": "Abu Dhabi", "city": "Abu Dhabi", "lat": 24.45118, "lon": 54.39696},
    {**REGIONS[0], "code": "AE-SHJ", "country": "AE", "name": "Sharjah", "short": "Sharjah", "city": "Sharjah", "lat": 25.3342, "lon": 55.41221},
    {**REGIONS[0], "code": "AE-NE", "country": "AE", "name": "Northern emirates", "short": "Northern emirates", "city": "Ras Al Khaimah (weather proxy)", "lat": 25.78953, "lon": 55.9432},
]
# Coordinates were returned by the registered Open-Meteo/GeoNames geocoder on 2026-10-04.
for _context in EMIRATE_CONTEXT:
    _context["coordinate_source"] = "open_meteo_geocoding"
    _context["coordinate_raw_ref"] = "https://geocoding-api.open-meteo.com/v1/search?name=" + {"AE-DXB": "Dubai", "AE-AUH": "Abu%20Dhabi", "AE-SHJ": "Sharjah", "AE-NE": "Ras%20Al%20Khaimah"}[_context["code"]] + "&count=1&language=en&format=json"
CONTEXT_REGIONS = REGIONS + EMIRATE_CONTEXT
CONTEXT_CODES = [r["code"] for r in CONTEXT_REGIONS]
MENA_CODES = ["AE", "SA", "EG", "JO", "MA"]


def region(code: str) -> dict:
    if code.startswith("AE-"):
        return next(r for r in EMIRATE_CONTEXT if r["code"] == code)
    return REGIONS[REGION_INDEX[code]]


def apply_priors(priors: dict | None) -> list[dict]:
    """Region list with dataset-derived overrides merged in (keys: age_bands, male_share, education, attitudes...)."""
    out = []
    for r in REGIONS:
        rr = dict(r)
        ov = (priors or {}).get(r["code"]) or {}
        for k in ("age_bands", "male_share", "education", "citizen_share", "platforms"):
            if k in ov and ov[k] is not None:
                rr[k] = ov[k]
        if ov.get("attitudes"):
            rr["attitudes"] = {**r["attitudes"], **ov["attitudes"]}
        out.append(rr)
    return out
