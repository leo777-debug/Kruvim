from unittest.mock import AsyncMock

from app.services.knowledge.learn import learn_round
from app.services.knowledge.store import GraphWriter
from app.services.llm import ProviderSettings, Usage, make_llm


async def test_one_batch_per_round_and_grounded_stances():
    posts = [{"id": 1, "author_ref": "p:1", "content": "Dubai has a useful learning festival."},
             {"id": 2, "author_ref": "p:2", "content": "Dubai does not have a useful learning festival."}]
    writer = GraphWriter("run", 2)
    writer.known.update(["post:1", "post:2", "agent:p:1", "agent:p:2"])
    llm = make_llm(ProviderSettings())
    await learn_round(writer, posts, llm, Usage())
    assert any(n["kind"] == "claim" and n["attributes"]["verified"] is False for n in writer.nodes)
    assert {e["relation"] for e in writer.edges} >= {"asserts", "supports", "opposes"}
    assert all(e["round"] == 2 for e in writer.edges)
    # Live extraction makes one request and rejects fabricated source ids/authors.
    llm.is_dry = False
    llm.complete_json = AsyncMock(return_value={"claims": [{"statement": "A claim", "post_ids": [1], "stances": [
        {"agent": "p:2", "post_id": 1, "relation": "supports"}]},
        {"statement": "Invented", "post_ids": [999], "stances": []}]})
    other = GraphWriter("run", 3)
    other.known.update(writer.known)
    await learn_round(other, posts, llm, Usage())
    llm.complete_json.assert_awaited_once()
    assert len(other.nodes) == 1
    assert [e["relation"] for e in other.edges] == ["asserts"]
