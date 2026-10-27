"""Free-text crowd builder: description -> filters + brief, and the brief reaches every voice agent's persona."""
import json

from app.services import crowd
from app.services.llm import BaseLLM, ProviderSettings, Usage


class StubLLM(BaseLLM):
    name = "stub"

    def __init__(self, reply: dict):
        super().__init__(ProviderSettings(provider="stub"))
        self.reply, self.seen = reply, []

    async def complete(self, *, system, user, role, max_tokens, usage, **kw):
        self.seen.append(json.loads(user))
        usage.add(self.name, "stub", role, 10, 0, 10, 0.0)
        return json.dumps(self.reply)


async def test_model_output_is_sanitized_and_merged():
    current = crowd.AudienceIn(regions=["AE"], interests=["music"], use_creator_audience=True).model_dump()
    llm = StubLLM({"filters": {"regions": ["SA", "Atlantis"], "age_min": 90, "age_max": 20, "genders": ["female", "robot"],
                               "interests": ["gaming", "astrology"], "ocean": {"openness": [0.9, 0.4], "charm": [0, 1]}},
                   "brief": "Saudi women who stream mobile games late at night.", "reply": "Set Saudi women 20-70 into gaming."})
    out = await crowd.interpret("saudi gamer girls", current, llm, Usage())
    a = out["audience"]
    assert a["regions"] == ["SA"] and a["genders"] == ["female"] and a["interests"] == ["gaming"]
    assert (a["age_min"], a["age_max"]) == (20, 70)
    assert a["ocean"] == {"openness": (0.4, 0.9)}
    assert a["use_creator_audience"] is True and a["brief"].startswith("Saudi women")
    assert out["mode"] == "model" and llm.seen[0]["current_filters"]["interests"] == ["music"]


def test_keywords_fallback_maps_common_phrases():
    current = crowd.AudienceIn(regions=["AE", "SA", "EG"]).model_dump()
    out = crowd.keywords("Gen Z women in Dubai who love skincare and gym content, mostly on TikTok", current)
    a = out["audience"]
    assert (a["age_min"], a["age_max"]) == (16, 27) and a["genders"] == ["female"]
    assert a["regions"] == ["AE-DXB"] and a["platforms"] == ["tiktok"]
    assert {"fashion_beauty", "fitness_health"} <= set(a["interests"])
    assert "skincare" in a["brief"] and out["mode"] == "keywords"
    again = crowd.keywords("they are also skeptical of influencer ads", a)
    assert again["audience"]["genders"] == ["female"] and "skincare" in again["audience"]["brief"] and "skeptical" in again["audience"]["brief"]
    dads = crowd.keywords("Skeptical Egyptian dads, 35-50", current)["audience"]
    assert dads["regions"] == ["EG"]
    assert crowd.keywords("make it Jordan too", dads)["audience"]["regions"] == ["EG", "JO"]
    assert crowd.keywords("only Jordan", dads)["audience"]["regions"] == ["JO"]


def test_brief_appears_in_persona_text():
    from app.services.population import persona_text
    p = {"id": 1, "name": "A", "handle": "a", "age": 22, "gender": "female", "origin": "Saudi", "city": "Riyadh", "region_name": "KSA",
         "language": "Arabic", "education": "bachelor's", "profession": "student", "income": "middle",
         "ocean": dict.fromkeys(crowd.OCEAN, 0.5), "platforms": ["tiktok"], "screen_time": "high", "interests": [],
         "stance": "neutral", "follows": 10, "followers": 5}
    assert "crowd you belong to" not in persona_text(p)
    assert "Night-shift nurses" in persona_text({**p, "crowd_brief": "Night-shift nurses who doomscroll on breaks."})


async def test_crowd_endpoint_dry_run(client, auth):
    h = auth[0]
    r = await client.post("/datapool/population/crowd", headers=h,
                          json={"message": "men 25-34 in Egypt into football", "audience": {"regions": ["AE"]}})
    assert r.status_code == 200, r.text
    a = r.json()["audience"]
    assert a["regions"] == ["EG"] and a["genders"] == ["male"] and (a["age_min"], a["age_max"]) == (25, 34)
    n = (await client.post("/datapool/population/count", headers=h, json=a)).json()["n"]
    assert n > 0


def test_traits_and_segments_are_validated():
    assert crowd.traits({"traits": {"activity": 2.0}}, {"sharing": 9, "contrarian": "lots", "forum": None}) == \
        {"activity": 2.0, "sharing": 3.0, "contrarian": None, "forum": None}
    good = [{"name": "Skeptics", "filters": {"stances": ["skeptic", "nope"]}}, {"name": "Fans", "filters": {"stances": ["enthusiast"]}}]
    out = crowd.segments(good + [{"name": "skeptics", "filters": {"stances": ["contrarian"]}}, {"name": "Empty", "filters": {}}, "junk"], [])
    assert [s["name"] for s in out] == ["Skeptics", "Fans"] and out[0]["filters"] == {"stances": ["skeptic"]}
    previous = [{"name": "Old", "filters": {}}]
    assert crowd.segments([good[0]], previous) == previous      # one usable segment is not a comparison


def test_keywords_build_traits_and_comparison():
    out = crowd.keywords("Gen Z in Dubai who doomscroll; compare the skeptics against the fans", crowd.AudienceIn(regions=["AE"]).model_dump())
    a = out["audience"]
    assert a["interests"] == []                                       # "Dubai" must not read as "ai"
    assert a["traits"]["activity"] == 1.8 and a["traits"]["contrarian"] == 0.35
    assert {s["name"] for s in a["segments"]} == {"Fans", "Skeptics"}


def test_engine_applies_traits_to_crowd():
    import numpy as np

    from app.services.simulation.engine import Engine
    e = Engine.__new__(Engine)
    n = 10_000
    e.rng, e.crowd_idx = np.random.default_rng(1), np.arange(n)
    e.c_act, e.c_share = np.full(n, 0.2, np.float32), np.full(n, 0.1, np.float32)
    e.c_contrarian, e.c_forum = np.zeros(n, bool), np.ones(n, bool)
    e.c_contrarian[:500] = True
    e.apply_traits({"activity": 2.0, "sharing": 0.5, "contrarian": 0.3, "forum": 0.25})
    assert np.allclose(e.c_act, 0.4) and np.allclose(e.c_share, 0.05)
    assert e.c_contrarian.sum() == 3000 and e.c_contrarian[:500].all()   # existing contrarians stay contrarian
    assert e.c_forum.sum() == 2500


async def test_described_segments_reach_results_and_report(client, auth):
    from test_e2e_dry import SCRIPT
    from test_e2e_features import FAST, run_all, wait_for
    h = auth[0]
    pid = (await client.post("/projects", json={"name": "Crowd"}, headers=h)).json()["id"]
    aud = {"regions": ["AE", "SA"], "brief": "Tech fans who doomscroll and argue in threads.",
           "traits": {"activity": 1.5, "contrarian": 0.3, "forum": 0.4},
           "segments": [{"name": "The fans", "filters": {"stances": ["enthusiast"]}},
                        {"name": "The skeptics", "filters": {"stances": ["skeptic", "contrarian"]}}]}
    body = {"name": "Crowd segments", "audience": aud, "overrides": FAST,
            "content": {"format": "podcast", "title": "Phone launch reaction", "transcript": SCRIPT}}
    sim = await client.post(f"/projects/{pid}/simulations", json=body, headers=h)
    assert sim.status_code == 200, sim.text
    s = await run_all(client, h, sim.json()["id"])
    segs = s["results"]["described_segments"]
    assert [x["name"] for x in segs] and {x["name"] for x in segs} == {"The fans", "The skeptics"}
    assert all(x["n"] > 0 and 0 <= x["score"] <= 10 for x in segs) and "note" in segs[0]
    assert sum(x["n"] for x in segs) < s["results"]["audience"]["size"]
    await wait_for(client, h, s["id"], "report_status", {"done"})
    rep = (await client.get(f"/simulations/{s['id']}/report", headers=h)).json()
    assert "Your segment" in json.dumps(rep["sections"])


def test_keywords_demonyms():
    c = crowd.AudienceIn(regions=["AE", "EG"]).model_dump()
    assert crowd.keywords("Saudi tech fans", c)["audience"]["regions"] == ["SA"]
    assert crowd.keywords("British expats in Dubai", c)["audience"]["regions"] == ["AE-DXB"]
