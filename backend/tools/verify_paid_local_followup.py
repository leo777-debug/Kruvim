"""Bounded hosted-provider verification; auth/provider secrets never leave backend memory.

An operator copies the existing encrypted provider into the exact disposable org
after ready.json is emitted. No plan or existing provider configuration is changed.
The hosted compatibility endpoint receives reviewed resized JPEGs, never originals.
"""

import asyncio
import base64
import json
import secrets
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

DIRECTORY = Path(__file__).resolve().parents[3] / "kruvim-paid-local-followup-20261117"
SINGLE = "--single" in sys.argv
BASE = "https://kruvim-lp.vercel.app/api/v1"


async def main():
    evidence = {
        "started": datetime.now(UTC).isoformat(),
        "source": "existing hosted API compatibility path",
        "requests": [],
        "checks": [],
    }
    project_id = session = None
    DIRECTORY.mkdir(exist_ok=True)
    (DIRECTORY / "continue").unlink(missing_ok=True)

    async with httpx.AsyncClient(base_url=BASE, timeout=180) as client:

        async def call(method, path, **kwargs):
            response = await client.request(method, path, **kwargs)
            evidence["requests"].append({"method": method, "path": path, "status": response.status_code})
            if response.status_code == 401 and session and path not in ["/auth/login", "/auth/register", "/auth/refresh"]:
                refreshed = await client.post("/auth/refresh", json={"refresh_token": session["refresh_token"]})
                if refreshed.is_success:
                    session.update(refreshed.json())
                    client.headers["Authorization"] = "Bearer " + session["access_token"]
                    response = await client.request(method, path, **kwargs)
                    evidence["requests"].append(
                        {"method": method, "path": path, "status": response.status_code, "session_refreshed": True}
                    )
            if response.is_error:
                # Never emit auth responses, provider settings or unsanitized upstream bodies.
                raise RuntimeError(f"{method} {path}: HTTP {response.status_code}")
            return response.json() if response.content else None

        try:
            session = await call(
                "POST",
                "/auth/register",
                json={
                    "email": f"local-paid-{uuid.uuid4().hex}@example.com",
                    "password": secrets.token_urlsafe(32),
                    "name": "Local preparation paid verification",
                    "org_name": "Temporary local preparation paid verification",
                },
            )
            client.headers.update({"Authorization": "Bearer " + session["access_token"], "X-Org-Id": session["orgs"][0]["id"]})
            fixture = {"user_id": session["user"]["id"], "org_id": session["orgs"][0]["id"], "provider_id": uuid.uuid4().hex}
            evidence.update(fixture)
            (DIRECTORY / "ready.json").write_text(json.dumps(fixture))
            print("Disposable cloud fixture ready; waiting for encrypted-provider copy.", flush=True)
            deadline = time.monotonic() + 600
            while not (DIRECTORY / "continue").exists():
                if time.monotonic() > deadline:
                    raise RuntimeError("Provider fixture timed out")
                await asyncio.sleep(0.5)
            config = (await call("GET", "/providers"))["configs"][0]
            assert config["api_key_set"] and config["preset"] == "mistral"
            evidence["models"] = {k: config[k] for k in ["voice_model", "report_model", "vision_model"]}
            tested = await call("POST", "/providers/" + fixture["provider_id"] + "/test")
            evidence["connection_test"] = {k: tested.get(k) for k in ["ok", "status", "message"]}
            if not tested.get("ok"):
                raise RuntimeError("Paid provider connection test failed")
            project = await call("POST", "/projects", json={"name": "Disposable browser-local paid verification"})
            project_id = project["id"]
            evidence["project_id"] = project_id
            derived = json.loads((DIRECTORY / "derived-fixtures.json").read_text())

            async def selected_image(image, label):
                data = base64.b64decode(image["data"].split(",", 1)[1], validate=True)
                assert len(data) < 300_000 and data[:2] == b"\xff\xd8"
                path = f"/projects/{project_id}/assets"
                target = await call(
                    "POST",
                    path + "/upload",
                    json={"filename": label + ".jpg", "mime": "image/jpeg", "size": len(data), "kind": "content"},
                )
                async with httpx.AsyncClient(timeout=90) as transfer:
                    r = await transfer.request(target["method"], target["url"], headers=target["headers"], content=data)
                    if r.is_error:
                        raise RuntimeError(f"Selected-image transfer failed: HTTP {r.status_code}")
                asset = await call("POST", path + "/complete", json={"ticket": target["ticket"]})
                evidence.setdefault("selected_images", []).append(
                    {"label": label, "bytes": len(data), "source": "browser canvas JPEG; original not transferred"}
                )
                return asset["id"]

            red = await selected_image(derived["slide-red.png"]["local_media"]["images"][0], "resized-red")
            blue = None if SINGLE else await selected_image(derived["slide-blue.jpg"]["local_media"]["images"][0], "resized-blue")
            frame = (
                None
                if SINGLE
                else await selected_image(derived["large-video.mp4"]["local_media"]["images"][0], "selected-video-frame")
            )
            # Test genuine vision first, independently of audience interpretation.
            visual = (
                None
                if SINGLE
                else await call(
                    "POST",
                    f"/projects/{project_id}/simulations",
                    json={
                        "name": "Selected-frame paid vision check",
                        "content": {
                            "format": "image_post",
                            "title": "Selected video frame",
                            "asset_id": frame,
                            "text": "Describe the visible test pattern; do not infer unshown video.",
                            "description": f"Frame time: {derived['large-video.mp4']['local_media']['images'][0]['time']} seconds",
                        },
                        "audience": {"regions": ["AE"]},
                        "overrides": {
                            "voice": 10,
                            "crowd": 0,
                            "stakeholders": 0,
                            "hours": 1,
                            "minutes_per_round": 60,
                            "active_per_round": 1,
                            "initial_reaction_sample": 10,
                            "listening": False,
                        },
                    },
                )
            )
            if visual:
                evidence["vision_simulation_id"] = visual["id"]
                await call("POST", f"/simulations/{visual['id']}/graph")

            async def wait(sid, field, target, seconds=3600):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    row = await call("GET", f"/simulations/{sid}")
                    evidence["last_state"] = {
                        k: row.get(k) for k in ["status", "report_status", "error", "usage", "results", "card"]
                    }
                    (DIRECTORY / "paid-evidence.json").write_text(json.dumps(evidence, indent=2))
                    if row.get(field) == target:
                        return row
                    if row.get("status") in ["failed", "paused", "cancelled"] or row.get("report_status") == "failed":
                        evidence["failed_state"] = {
                            k: row.get(k) for k in ["status", "report_status", "error", "pause_state", "usage", "results"]
                        }
                        raise RuntimeError(f"Cloud run stopped: {row.get('status')}/{row.get('report_status')}")
                    await asyncio.sleep(5)
                raise RuntimeError(f"Cloud stage timeout: {field}={target}")

            if visual:
                vision = await wait(visual["id"], "status", "graph_ready")
                evidence["vision_card"] = vision["card"]
                evidence["vision_usage"] = vision.get("usage")
                assert vision["card"]["visual_analysis"]["status"] == "analysed"
                assert vision["card"]["visual_analysis"]["images"] == 1
                assert "[dry run]" not in vision["card"]["summary"].lower()
                print("Paid selected-frame vision passed.", flush=True)
            # Derived PDF text is sent as plain content because the pre-release
            # hosted compatibility API does not yet expose extracted-text storage.
            sim = await call(
                "POST",
                f"/projects/{project_id}/simulations",
                json={
                    "name": "Browser-derived paid simulation" if SINGLE else "Browser-derived A/B paid simulation",
                    "requirement": "Explain how the audience reacts to this breakfast post. Keep the report short."
                    if SINGLE
                    else "Compare the red and blue breakfast posts. Explain which version works better and why.",
                    "content": {
                        "format": "image_post",
                        "title": "Quick breakfast A",
                        "asset_id": red,
                        "text": derived["brief.pdf"]["text"] + "\nMake breakfast with oats and banana.",
                        "variant_b": None
                        if SINGLE
                        else {
                            "title": "Quick breakfast B",
                            "asset_id": blue,
                            "text": "Make breakfast with oats and banana. Save this recipe.",
                        },
                    },
                    "audience": {"regions": ["AE"], "age_min": 18, "age_max": 45},
                    "overrides": {
                        "voice": 10,
                        "crowd": 20,
                        "stakeholders": 0,
                        "hours": 1,
                        "minutes_per_round": 60,
                        "active_per_round": 1,
                        "initial_reaction_sample": 10,
                        "listening": False,
                    },
                },
            )
            evidence["simulation_id"] = sim["id"]
            await call("POST", f"/simulations/{sim['id']}/autopilot")
            result = await wait(sim["id"], "report_status", "done", 3600)
            evidence["completed"] = {k: result.get(k) for k in ["status", "report_status", "usage", "results", "card"]}
            assert result["status"] == "completed"
            assert result["card"]["visual_analysis"]["status"] == "analysed"
            if not SINGLE:
                assert result["content"]["card_b"]["visual_analysis"]["status"] == "analysed"
            report = await call("GET", f"/simulations/{sim['id']}/report")
            evidence["analyst_report"] = {k: report.get(k) for k in ["status", "markdown", "model", "error"]}
            assert report.get("markdown") and "[dry run]" not in report["markdown"].lower()
            assert not (result["results"].get("provider") or {}).get("dry", True)
            reliability = result["results"].get("reliability") or {}
            assert reliability.get("fallback_calls") == 0, "Deterministic fallbacks occurred"
            assert reliability.get("failed_provider_calls") == 0, "Provider calls failed"
            assert all(stage.get("failed", 0) == 0 for stage in result["usage"].values()), "A stage recorded provider failures"
            evidence["success"] = True
            print("Genuine paid simulation and analyst report completed.", flush=True)
        except Exception as exc:
            evidence["success"] = False
            evidence["error"] = str(exc)[:500]
            print("Paid verification stopped: " + evidence["error"], flush=True)
        finally:
            terminal = (
                evidence.get("success")
                or (evidence.get("last_state") or {}).get("status") in ["failed", "paused", "cancelled"]
                or (evidence.get("last_state") or {}).get("report_status") == "failed"
            )
            if project_id and terminal:
                try:
                    evidence["project_cleanup"] = await call("DELETE", "/projects/" + project_id)
                except Exception:
                    evidence["project_cleanup"] = "pending"
            elif project_id:
                evidence["project_cleanup"] = "preserved: unfinished work must not be deleted"
            if session:
                try:
                    await call("POST", "/auth/logout", json={"refresh_token": session["refresh_token"]})
                    evidence["logged_out"] = True
                except Exception:
                    evidence["logged_out"] = False
            (DIRECTORY / "paid-evidence.json").write_text(json.dumps(evidence, indent=2))
            print("Sanitized evidence written; server-side provider/user cleanup still required.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
