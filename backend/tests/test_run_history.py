from datetime import UTC, datetime

from app.db.session import session_scope
from app.models import Simulation


async def test_all_runs_filters_sort_pagination_and_workspace_isolation(client, auth):
    headers, _ = auth
    projects = [(await client.post("/projects", headers=headers, json={"name": "History " + n})).json() for n in ("Learning", "Travel")]
    configs = [("Useful Python", "youtube", "long_video", 8.2, "approved", 1),
               ("Short tutorial", "tiktok", "short_video", 6.1, "in_review", 2),
               ("Trip draft", "instagram", "image_post", None, "none", 3)]
    ids = []
    for name, platform, format_, score, review, day in configs:
        run = (await client.post(f"/projects/{projects[0 if day < 3 else 1]['id']}/simulations", headers=headers,
                json={"name": name, "content": {"format": format_, "platform": platform, "text": "Example", "title": name}})).json()
        ids.append(run["id"])
        async with session_scope() as s:
            sim = await s.get(Simulation, run["id"])
            sim.created_at = datetime(2026, 9, day, 23, 59, tzinfo=UTC)
            sim.status, sim.review_status = "completed" if score is not None else "draft", review
            sim.score = score
            sim.results = {"score": {"mean": score}, "models": {"private": "never materialise"}}
    base = f"/runs?project_id={projects[0]['id']}"
    all_ = (await client.get(base + "&sort=score_high", headers=headers)).json()
    assert all_["total"] == 2 and [r["id"] for r in all_["items"]] == ids[:2]
    assert "models" not in str(all_)
    filtered = (await client.get(base + "&format=long_video&platform=youtube&status=completed&review_status=approved&score_min=8&score_max=9&date_from=2026-09-01&date_to=2026-09-01&q=Python", headers=headers)).json()
    assert filtered["total"] == 1 and filtered["items"][0]["id"] == ids[0]
    page = (await client.get(base + "&sort=oldest&limit=1&offset=1", headers=headers)).json()
    assert page["total"] == 2 and page["items"][0]["id"] == ids[1]
    assert (await client.get(base + "&q=Travel", headers=headers)).json()["total"] == 0
    assert (await client.get("/runs?q=History Travel", headers=headers)).json()["items"][0]["score"] is None
    assert (await client.get(base + "&score_min=9&score_max=1", headers=headers)).status_code == 400
    assert (await client.get(base + "&date_from=2026-10-01&date_to=2026-09-01", headers=headers)).status_code == 400
    assert (await client.get(base + "&limit=99999", headers=headers)).status_code == 422
    assert (await client.get(base + "&sort=unknown", headers=headers)).status_code == 422
    stranger = (await client.post("/auth/register", json={"email": "runs-other@example.com", "password": "correct-horse-battery",
                                "name": "Other", "org_name": "Other Runs"})).json()
    other = {"Authorization": "Bearer " + stranger["access_token"]}
    assert (await client.get(base, headers=other)).json()["total"] == 0
    assert (await client.get("/runs")).status_code == 401
