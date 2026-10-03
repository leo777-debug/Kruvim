import numpy as np
import pytest

from app.core.security import hash_password, verify_password
from app.services.llm import extract_json
from app.services.population.calibrate import summarize
from app.services.population.generator import generate
from app.services.population.regions import STANCES


def test_downvoted_posts_do_not_crash_ranking():
    from app.services.simulation.engine import PostRT

    post = PostRT(id=1, platform="forum", kind="post", author_ref="p:1", author_name="Test",
                  author_region="AE", content="An unpopular proposal", round=0, stance=0, down=100)
    assert post.popularity() == 0
    post.likes = 100
    assert post.popularity() > 0


def test_password_hashing():
    h = hash_password("hunter2-but-longer")
    assert verify_password("hunter2-but-longer", h)
    assert not verify_password("wrong", h)


@pytest.mark.parametrize("raw", [
    '{"a": 1}', '```json\n{"a": 1}\n```', '<think>hmm</think>{"a": 1}', 'Sure! Here you go: {"a": 1,} thanks',
])
def test_extract_json_tolerant(raw):
    assert extract_json(raw)["a"] == 1


def test_population_anti_herd_and_graph():
    pop = generate(20_000, 3)
    shares = np.bincount(pop.stance, minlength=len(STANCES)) / pop.n
    assert abs(shares[STANCES.index("contrarian")] - 0.1) < 1e-3
    assert abs(shares[STANCES.index("skeptic")] - 0.1) < 1e-3
    assert pop.followers_n.max() > 20 * max(1, np.median(pop.followers_n))   # heavy tail
    p = pop.persona(5)
    assert p["name"] and p["handle"] and "attitudes" in p


def test_barometer_summary():
    csv = "country,age,sex,wt,rel\n" + "\n".join(f"Egypt,{20 + i % 40},{1 + i % 2},1,{1 + i % 4}" for i in range(300))
    s = summarize(csv.encode(), {"country_col": "country", "age_col": "age", "sex_col": "sex", "male_values": ["1"], "weight_col": "wt",
                                 "attitudes": {"religiosity": {"col": "rel", "min": 1, "max": 4}}})
    eg = s["regions"]["EG"]
    assert eg["respondents"] == 300
    assert abs(eg["male_share"] - 0.5) < 0.01
    assert abs(sum(eg["age_bands"]) - 1) < 1e-6
    assert 0 <= eg["attitudes"]["religiosity"] <= 1
