"""Run a small five-stage study in an isolated SQLite DB with the configured model.

python -m tools.model_smoke; requires KRUVIM_LLM_PROVIDER, BASE_URL and model names.
Keys are read from configuration and never printed. Costs are null unless prices are configured.
"""
import asyncio
import json
import os
import tempfile
import time

_scratch = tempfile.mkdtemp(prefix="kruvim-model-smoke-")
os.environ.update(KRUVIM_ENV="test", KRUVIM_DATABASE_URL="sqlite+aiosqlite:///" + os.path.join(_scratch, "smoke.db").replace("\\", "/"),
    KRUVIM_DATA_DIR=_scratch, KRUVIM_POPULATION_SIZE="40000", KRUVIM_REDIS_URL="",
    KRUVIM_FIRST_SUPERUSER_EMAIL="", KRUVIM_FIRST_SUPERUSER_PASSWORD="")


async def main():
    from unittest.mock import AsyncMock, patch

    import httpx

    from app.core.config import settings
    from app.main import app
    from app.services import jobs
    if settings.llm_provider == "dryrun":
        raise SystemExit("Choose a configured model with KRUVIM_LLM_PROVIDER and model settings. No key is required for local servers.")
    start = time.monotonic()
    with patch("app.services.datapool.run_due", new=AsyncMock(return_value=[])), patch("app.services.datapool.context.ensure_fresh", new=AsyncMock()), patch("app.services.datapool.targeted.prepare", new=AsyncMock()):
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://smoke/api/v1") as client:
            account = (await client.post("/auth/register", json={"email": "smoke@example.com", "password": "disposable-smoke-password", "name": "Smoke", "org_name": "Smoke"})).json()
            headers = {"Authorization": "Bearer " + account["access_token"]}
            project = (await client.post("/projects", headers=headers, json={"name": "Model smoke"})).json()
            response = await client.post(f"/projects/{project['id']}/simulations", headers=headers, json={"content": {
                "type": "video", "format": "short_video", "platform": "tiktok", "title": "Quick breakfast",
                "transcript": "Start with oats and yogurt. Add a banana, mix, and breakfast is ready in a minute. Try this on your next busy morning."},
                "audience": {"regions": ["AE"], "age_min": 18}, "overrides": {"voice": 10, "crowd": 100, "stakeholders": 0, "hours": 1, "listening": False}})
            response.raise_for_status()
            sid = response.json()["id"]
            for stage, expected in (("graph", "graph_ready"), ("environment", "ready"), ("start", "completed")):
                response = await client.post(f"/simulations/{sid}/{stage}", headers=headers)
                response.raise_for_status()
                await jobs.drain()
                result = (await client.get(f"/simulations/{sid}", headers=headers)).json()
                if result["status"] != expected:
                    print(json.dumps({"stage": stage, "status": result["status"], "error": result.get("error"), "duration_seconds": time.monotonic() - start}))
                    raise SystemExit(1)
            voices = (await client.get(f"/simulations/{sid}/agents", headers=headers)).json()
            chat = await client.post(f"/simulations/{sid}/agents/{voices[0]['ref']}/chat", headers=headers, json={"message": "What would improve it?"})
            chat.raise_for_status()
            print(json.dumps({"usage_by_stage": result["usage"], "duration_seconds": round(time.monotonic() - start, 2),
                "report": result["report_status"], "reliability": result["results"].get("reliability"), "interview": bool(chat.json().get("reply"))}, indent=2))
            if result["report_status"] != "done":
                raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
