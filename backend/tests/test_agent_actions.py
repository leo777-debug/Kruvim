from datetime import UTC, datetime

import numpy as np

from app.services.knowledge.store import GraphWriter
from app.services.llm import ProviderSettings, Usage, make_llm
from app.services.simulation.engine import AgentRT, Engine, PostRT


async def test_discovery_mute_and_comment_votes(client, auth):
    headers, _ = auth
    project = (await client.post("/projects", headers=headers, json={"name": "Actions"})).json()
    run = (await client.post(f"/projects/{project['id']}/simulations", headers=headers,
                            json={"content": {"type": "text", "text": "Python learning"}})).json()
    engine = Engine(run["id"], make_llm(ProviderSettings()), Usage())
    engine.start, engine.mpr, engine.round = datetime.now(UTC), 60, 1
    weights = {"echo_chamber": .5, "recency_weight": .3, "popularity_weight": .4, "relevance_weight": .3}
    engine.cfg = {"behaviour": {"max_actions": 8}, "platforms": {"feed": weights},
                  "context": {"SA": {"trending": [{"title": "Python workshop", "value": 100}]}}}
    engine.rng = np.random.default_rng(9)
    engine.writer = GraphWriter(run["id"], 1)
    a = AgentRT(1, "p:1", "voice", "Alice", "alice", "SA", {}, {}, 10)
    b = AgentRT(2, "p:2", "voice", "Bob", "bob", "SA", {}, {}, 10)
    engine.agents = {a.ref: a, b.ref: b}
    p = PostRT(101, "feed", "comment", b.ref, b.name, "SA", "Python practice improves learning.", 0, 7)
    hidden = PostRT(102, "forum", "comment", b.ref, b.name, "SA", "Python forum", 0, 7)
    engine.posts, engine.by_platform["feed"] = {101: p, 102: hidden}, [101]
    done = await engine.apply_turn(a, "feed", [], {"actions": [
        {"type": "SEARCH_POSTS", "query": "Python"}, {"type": "LIKE_COMMENT", "post_id": 101},
        {"type": "LIKE_COMMENT", "post_id": 101}, {"type": "LIKE_COMMENT", "post_id": 102},
        {"type": "VIEW_TRENDS"}, {"type": "SEARCH_USER", "query": "bob"}, {"type": "REFRESH"}]})
    assert p.likes == 1 and hidden.likes == 0
    assert [x["type"] for x in done].count("LIKE_COMMENT") == 1
    assert done[0]["results"][0]["id"] == 101
    assert any("Python workshop" in x for x in a.memory)
    before = p.popularity()
    await engine.apply_turn(a, "feed", [engine.post_view(p)], {"actions": [{"type": "DISLIKE_COMMENT", "post_id": 101}]})
    assert p.likes == 0 and p.down == 1 and p.popularity() < before
    await engine.apply_turn(a, "feed", [], {"actions": [{"type": "MUTE", "handle": "bob"}]})
    assert b.ref in a.muted and not engine.recommend(a, "feed", 6)
    assert not engine.search_posts(a, "feed", "Python")
    assert not engine.search_users(a, "bob")
    actions = (await client.get(f"/simulations/{run['id']}/actions?action=SEARCH_POSTS", headers=headers)).json()
    assert len(actions) == 1 and actions[0]["meta"]["results"][0]["id"] == 101
    # Dry-run can discover and vote on comments without a provider.
    from app.services.simulation.dry import action
    kinds = set()
    for seed in range(150):
        kinds.update(x["type"] for x in action(a, [engine.post_view(p)], "feed", np.random.default_rng(seed))["actions"])
    assert kinds >= {"SEARCH_POSTS", "SEARCH_USER", "VIEW_TRENDS", "REFRESH", "MUTE", "LIKE_COMMENT"}
