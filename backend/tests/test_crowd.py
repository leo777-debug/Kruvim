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
