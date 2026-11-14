from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from app.schemas.simulation import OverridesIn
from app.services.llm import ProviderSettings, Usage, make_llm
from app.services.simulation.engine import Engine
from app.services.simulation.activation import active_limit, estimate, initial_sample


def configured():
    e = Engine("selective-test", make_llm(ProviderSettings()), Usage())
    e.cfg = {"agents": {"voice": 100, "stakeholders": 0, "crowd": 0},
             "overrides": {"active_per_round": 7, "initial_reaction_sample": 10, "hours": 10}}
    e.seed = 42
    e.rng = np.random.default_rng(42)
    e.agents = {str(i): SimpleNamespace(ref=str(i), kind="voice", reaction={}, cfg={"activity": 1.}, region="AE") for i in range(100)}
    e.curve = lambda region, r: 1.
    return e


def test_sampling_preserves_population_and_lets_unsampled_agents_act():
    e = configured()
    initial = {a.ref for a in e.first_voices()}
    assert len(initial) == 10 and len(e.agents) == 100
    turns = [e.select_round_agents(r) for r in range(10)]
    assert all(len(t) == len(set(t)) == 7 for t in turns)
    assert set().union(*map(set, turns)) - initial
    other = configured()
    assert initial == {a.ref for a in other.first_voices()}
    assert turns == [other.select_round_agents(r) for r in range(10)]
    e.curve = lambda region, r: 0.
    assert e.select_round_agents(11) == []


def test_estimate_matches_execution_limits_and_legacy_defaults():
    e = configured()
    plan = estimate(e.cfg)
    assert plan["active_per_round_limit"] == active_limit(e.cfg) == 7
    assert plan["initial_impression_sample"] == initial_sample(e.cfg) == 10
    assert len(e.agents) == 100
    legacy = {"agents": e.cfg["agents"]}
    assert active_limit(legacy) == initial_sample(legacy) == 100


@pytest.mark.parametrize("field,value", [("active_per_round", 0), ("active_per_round", 257), ("initial_reaction_sample", 9)])
def test_invalid_sampling_settings_rejected(field, value):
    with pytest.raises(ValidationError):
        OverridesIn(**{field: value})


async def test_api_accepts_sampling_and_reports_matching_estimate(client, auth):
    headers, _ = auth
    body = {"content": {"type": "text", "text": "A breakfast recipe"},
            "overrides": {"voice": 100, "stakeholders": 0, "hours": 10,
                          "active_per_round": 7, "initial_reaction_sample": 10}}
    response = await client.post("/simulations/estimate", headers=headers, json=body)
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["active_per_round_limit"] == 7
    assert plan["initial_impression_sample"] == 10
    assert plan["discussion_turn_ceiling"] == 70
