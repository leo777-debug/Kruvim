"""Only synthetic fixture numbers are used here; never seed factual observations."""
from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np

from app.services.population.generator import generate
from app.services.population.uae import DOMAINS, EMIRATES, LABEL, PLACEHOLDER_ID, rake, reconcile


def observation(id_, source, value, sex="male", geography="AE"):
    return SimpleNamespace(id=id_, source_id=source, metric="population_share", unit="percent", value=value,
        geography=geography, dimensions={"sex": sex}, period_end=datetime(2025, 12, 31, tzinfo=UTC))


def test_raking_conditional_joint_marginals_and_missing_support():
    import pytest
    data = {"sex": np.tile([0, 0, 1, 1], 250), "emirate": np.tile([0, 1, 0, 1], 250)}
    targets = [{"mask": data["sex"] == 1, "fraction": .7},
               {"mask": data["emirate"] == 0, "fraction": .4},
               {"scope": data["emirate"] == 0, "mask": data["sex"] == 1, "fraction": .8}]
    weights, residual = rake(data, targets)
    assert residual < 1e-5
    for t in targets:
        scope = t.get("scope", np.ones(1000, bool))
        assert abs(weights[t["mask"] & scope].sum() / weights[scope].sum() - t["fraction"]) < 1e-5
    with pytest.raises(ValueError, match="absent seed support"):
        rake(data, [{"mask": np.zeros(1000, bool), "fraction": .2}])


def test_conflicts_retained_and_licence_gate_and_uncertainty():
    def source(id_, reliability):
        return SimpleNamespace(id=id_, name=id_, publisher="Fixture", url="https://example.com", attribution="Fixture",
            geography_level="country", reliability=reliability, status="active", licence_approved=True)
    sources = {"a": source("a", .9), "b": source("b", .8)}
    now = datetime(2026, 1, 1, tzinfo=UTC)
    targets, agreed = reconcile([observation("o1", "a", 70), observation("o2", "b", 71)], sources, now)
    assert not agreed["conflicts"]
    targets, conflict = reconcile([observation("o1", "a", 70), observation("o2", "b", 90)], sources, now)
    assert targets[0]["fraction"] == .7
    assert len(conflict["conflicts"][0]["values"]) == 2
    assert set(conflict["observation_ids"]) == {"o1", "o2"}
    assert conflict["attribute_confidence"]["sex"]["confidence"] < agreed["attribute_confidence"]["sex"]["confidence"]
    sources["a"].licence_approved = sources["b"].licence_approved = False
    targets, p = reconcile([observation("o1", "a", 70)], sources, now)
    assert targets == [] and p["status"] == "placeholder" and p["source_ids"] == [PLACEHOLDER_ID]


def test_emirate_union_filters_determinism_native_fit_and_legacy_cache(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.services.population.store import FIELDS, _path, load_from_disk
    a = generate(10000, 42)
    b = generate(10000, 42)
    for key in a.uae:
        np.testing.assert_equal(a.uae[key], b.uae[key])
    ae = a.mask({"regions": ["AE"]})
    subregions = [a.mask({"regions": [code]}) for code in EMIRATES]
    np.testing.assert_array_equal(ae, np.logical_or.reduce(subregions))
    assert sum(int(x.sum()) for x in subregions) == ae.sum()
    i = int(np.flatnonzero(ae)[0])
    p = a.persona(i)
    assert p["population_label"] == LABEL and p["population_status"] == "placeholder"
    assert p["nationality_group"] in DOMAINS["nationality_group"]
    assert p["residence_emirate"] in EMIRATES and p["remittance_share"] is None
    assert a.mask({"nationality_groups": [p["nationality_group"]], "emirates": [p["residence_emirate"]], "languages": [p["language"]]})[i]
    c = generate(10000, 42, {"_uae_targets": [{"geography": "AE", "dimensions": {"sex": "male"}, "fraction": .8}]})
    assert abs(c.male[c.region == 0].mean() - .8) < .015
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    np.savez(_path("old"), **{f: getattr(a, f) for f in FIELDS})
    old = load_from_disk("old", a.n, a.seed, {})
    np.testing.assert_array_equal(old.region, a.region)
    np.testing.assert_array_equal(old.age, a.age)
    assert old.persona(i)["population_label"] == LABEL


async def test_population_api_placeholder_rebuild_review_rollback_and_org_filters(client, auth):
    from app.services import jobs
    headers = auth[0]
    first = (await client.get("/datapool/population", headers=headers)).json()
    assert first["stats"]["status"] == "placeholder" and first["stats"]["label"] == LABEL
    counts = [(await client.post("/datapool/population/count", headers=headers, json={"regions": [c]})).json()["n"] for c in ["AE", *EMIRATES]]
    assert counts[0] == sum(counts[1:])
    build = await client.post("/datapool/population/rebuild", headers=headers, json={})
    assert build.status_code == 200, build.text
    await jobs.drain()
    version = build.json()["version_id"]
    next_ = (await client.get("/datapool/population", headers=headers)).json()
    assert next_["active"]["id"] == first["active"]["id"]
    assert (await client.post(f"/datapool/population/versions/{version}/activate", headers=headers)).status_code == 200
    assert (await client.get("/datapool/population", headers=headers)).json()["active"]["id"] == version
    assert (await client.post(f"/datapool/population/versions/{first['active']['id']}/activate", headers=headers)).status_code == 200
    profile = await client.put("/my-audience", headers=headers, json={"split": {"countries": {"AE": 100}}, "filters": {"emirates": ["AE-SHJ"]}})
    assert profile.status_code == 200, profile.text
    assert (await client.get("/my-audience", headers=headers)).json()["profile"]["filters"]["emirates"] == ["AE-SHJ"]
    assert (await client.post("/datapool/population/count", headers=headers, json={"emirates": ["bad"]})).status_code == 422
