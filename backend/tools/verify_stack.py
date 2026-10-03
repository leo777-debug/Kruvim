"""Bounded, repeatable local/staging API load and format checks. Uses a test account.

Run with KRUVIM_VERIFY_EMAIL / KRUVIM_VERIFY_PASSWORD. Creates a new project and
17 dry-run simulations; refuses any workspace with a paid/model provider enabled.
Outputs timings and created IDs as JSON (never credentials).
"""
import argparse
import asyncio
import json
import os
import statistics
import time
from collections import Counter
from pathlib import Path

import httpx

TEXT = "A short guide to learning Python. Start with a small useful project, practice daily, and test your assumptions. Share your progress with a friend."
FAST = {"voice": 16, "crowd": 400, "stakeholders": 1, "hours": 2, "minutes_per_round": 60, "listening": False}


async def main(args):
    async with httpx.AsyncClient(base_url=args.base.rstrip("/") + "/api/v1", timeout=120) as c:
        async def call(method, path, **kwargs):
            r = await c.request(method, path, **kwargs)
            r.raise_for_status()
            return r.json()

        session = await call("POST", "/auth/login", json={"email": os.environ["KRUVIM_VERIFY_EMAIL"], "password": os.environ["KRUVIM_VERIFY_PASSWORD"]})
        c.headers["Authorization"] = "Bearer " + session["access_token"]
        usage = await call("GET", "/usage")
        # Settings/provider response contains secrets only as masks, but is never emitted.
        provider = (await call("GET", "/providers"))["active"]
        if provider.get("preset") != "dryrun" and provider.get("provider") != "dryrun":
            raise RuntimeError("Use a dedicated dry-run workspace for this load check.")
        ref = await call("GET", "/reference")
        project = await call("POST", "/projects", json={"name": "Verification " + time.strftime("%Y%m%d-%H%M%S")})
        result = {"project_id": project["id"], "formats": [], "population": (await call("GET", "/datapool/population"))["stats"]["n"], "mode": "dryrun"}
        sem = asyncio.Semaphore(args.concurrency)

        async def run(f):
            async with sem:
                start = time.perf_counter()
                content = {"format": f["key"], "platform": f["platform"], "title": f["label"] + " verification", "creator_followers": 12000}
                if f.get("poll"):
                    content.update(text="Which learning method do you prefer?", poll_options=["Books", "Videos", "Practice"])
                elif f["type"] in ("video", "audio"):
                    content["transcript"] = TEXT
                elif f["type"] == "image":
                    content["description"] = "A clear blue poster saying Learn Python. A smiling student and three simple steps."
                else:
                    content["text"] = TEXT
                sim = await call("POST", f"/projects/{project['id']}/simulations", json={"name": f["label"] + " verification", "content": content, "audience": {"regions": ["AE", "SA"]}, "overrides": FAST})
                await call("POST", f"/simulations/{sim['id']}/autopilot")
                while time.perf_counter() - start < 240:
                    s = await call("GET", f"/simulations/{sim['id']}")
                    if s["status"] == "failed":
                        raise AssertionError(f"{f['key']}: {s['error']}")
                    if s["status"] == "completed" and s["report_status"] == "done":
                        assert s["results"]["format"]["key"] == f["key"]
                        assert s["results"]["viral"]["cascade"]["real_world"]["followers"] == 12000
                        entry = {"format": f["key"], "id": sim["id"], "seconds": round(time.perf_counter() - start, 2), "status": "passed"}
                        result["formats"].append(entry)
                        print(json.dumps(entry), flush=True)
                        return
                    await asyncio.sleep(1)
                raise TimeoutError(f"{f['key']}: did not complete in 240 seconds")

        await asyncio.gather(*(run(f) for f in ref["formats"]))
        # Separate bounded read burst, so throughput is not confused with model work.
        read_sem = asyncio.Semaphore(args.read_concurrency)
        paths = ["/projects", "/alerts", "/watches", "/reference"]

        async def read(i):
            async with read_sem:
                start = time.perf_counter()
                r = await c.get(paths[i % len(paths)])
                return r.status_code, (time.perf_counter() - start) * 1000

        start = time.perf_counter()
        reads = await asyncio.gather(*(read(i) for i in range(args.requests)))
        elapsed = time.perf_counter() - start
        latencies = sorted(t for _, t in reads)
        result["load"] = {"requests": len(reads), "concurrency": args.read_concurrency, "statuses": dict(Counter(s for s, _ in reads)), "seconds": round(elapsed, 2), "requests_per_second": round(len(reads) / elapsed, 2), "median_ms": round(statistics.median(latencies), 2), "p95_ms": round(latencies[int(len(latencies) * .95) - 1], 2)}
        result["credits_before"] = usage["credits_balance"]
        result["credits_after"] = (await call("GET", "/usage"))["credits_balance"]
        Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result["load"], indent=2))
        assert all(s in (200, 429) for s, _ in reads), result["load"]


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--concurrency", type=int, default=3)
    p.add_argument("--read-concurrency", type=int, default=20)
    p.add_argument("--requests", type=int, default=160)
    p.add_argument("--output", default="verification-results.json")
    asyncio.run(main(p.parse_args()))
