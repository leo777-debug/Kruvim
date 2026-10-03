"""Offline feature-hashing embeddings; stored in snapshots for reproducible per-person retrieval."""
import hashlib
import time

import httpx
import numpy as np
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import settings
from app.db.session import session_scope
from app.models import Signal, SignalEmbedding
from app.services.datapool.context import tokens


def embed(text: str, dimensions=128):
    vector = np.zeros(dimensions, dtype=np.float32)
    for token in tokens(text):
        digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
        number = int.from_bytes(digest, "little")
        vector[number % dimensions] += 1 if number & 128 else -1
    norm = float(np.linalg.norm(vector))
    if norm:
        vector /= norm
    return vector


def rank(signals, query, weights=None, n=5):
    query_vector = embed(query)
    scored = []
    for signal in signals:
        vec = signal.get("embedding")
        vector = np.asarray(vec, dtype=np.float32) if vec is not None else embed(signal.get("title", "") + " " + signal.get("summary", ""))
        score = float(vector @ query_vector) * (weights or {}).get(signal.get("source"), 1)
        scored.append((score, str(signal.get("id", "")), signal))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [{k: v for k, v in x[2].items() if k != "embedding"} for x in scored[:n]]


async def prepare_retrieval(org_id, personas, card, snapshots, llm, usage):
    """At most one provider embedding request for all signals and all agent queries."""
    signals = {str(x["id"]): x for snap in snapshots.values() for x in snap.get("signals", [])}
    candidates = list(signals.values())[:min(300, 2048 - len(personas))]
    queries = [" ".join(x.get("label", "") for x in p.get("interests", [])) + " " + card.get("title", "") + " " +
               " ".join(card.get("keywords") or []) + " " + " ".join(p.get("platforms", [])) + f" age {p['age']}" for p in personas]
    texts = [(x.get("title", "") + " " + x.get("summary", ""))[:1500] for x in candidates] + queries
    vectors = [embed(text) for text in texts]
    model, cost = "local-hash-v1", 0.0
    if settings.embedding_model and not llm.is_dry and llm.s.provider in ("openai", "openai_compatible") and llm.s.base_url and candidates:
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(llm.s.base_url.rstrip('/') + "/embeddings", headers={"Authorization": f"Bearer {llm.s.api_key}"},
                    json={"model": settings.embedding_model, "input": texts, "dimensions": 128})
                response.raise_for_status()
                data = response.json()
                remote = [np.asarray(x["embedding"], np.float32) for x in sorted(data["data"], key=lambda x: x["index"])]
                if len(remote) != len(texts) or any(v.shape != (128,) or not np.isfinite(v).all() for v in remote):
                    raise ValueError("Embedding dimensions differ from the configured index")
                vectors = [v / max(float(np.linalg.norm(v)), 1e-9) for v in remote]
                model = settings.embedding_model
                tokens = int(data.get("usage", {}).get("total_tokens", 0))
                cost = tokens * settings.embedding_price_per_million / 1e6 if settings.embedding_price_per_million is not None else None
                usage.add(llm.s.provider, model, "retrieval_embedding", tokens, 0, 0, time.monotonic() - start)
                usage.by_role["retrieval_embedding"]["cost_usd"] = cost
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            pass  # local fallback never prevents a simulation
    # Persist provider/local vectors within the workspace. Prepared evidence is frozen in agent config.
    async with session_scope() as s:
        ids = [int(x["id"]) for x in candidates if str(x["id"]).isdigit()]
        visible = set((await s.execute(select(Signal.id).where(Signal.id.in_(ids), or_(Signal.org_id.is_(None), Signal.org_id == org_id)))).scalars())
        values = []
        for signal, vector in zip(candidates, vectors[:len(candidates)]):
            if not str(signal["id"]).isdigit() or int(signal["id"]) not in visible:
                continue
            key = f"{org_id}:{signal['id']}:{hashlib.sha256(model.encode()).hexdigest()[:12]}"
            values.append(dict(id=key, org_id=org_id, signal_id=int(signal["id"]), model=model, vector=vector.tolist()))
        if values:
            insert = sqlite_insert if settings.is_sqlite else pg_insert
            await s.execute(insert(SignalEmbedding).values(values).on_conflict_do_nothing(index_elements=["id"]))
    out = []
    region_ids = {code: {str(x["id"]) for x in snap.get("signals", [])} for code, snap in snapshots.items()}
    for persona, query in zip(personas, vectors[len(candidates):]):
        candidates_here = [(i, x) for i, x in enumerate(candidates) if str(x["id"]) in region_ids.get(persona["region"], set())]
        weights = snapshots.get(persona["region"], {}).get("source_weights", {})
        ranked = sorted(candidates_here, key=lambda pair: (-float(vectors[pair[0]] @ query) * weights.get(pair[1].get("source"), 1), str(pair[1]["id"])))
        out.append([{k: v for k, v in signal.items() if k != "embedding"} for _, signal in ranked[:5]])
    return out, {"model": model, "extra_cost_usd": cost, "provider_calls": int(model != "local-hash-v1")}
