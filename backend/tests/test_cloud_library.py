from unittest.mock import AsyncMock

from sqlalchemy import select

from app.core.config import settings
from app.db.session import session_scope
from app.models import CloudJob, LibraryEntry, LibraryFolder
from app.services import cloud_jobs, supabase_storage
from app.services.library import retrieve, sync_due


async def test_cloud_inbox_and_direct_rows_are_selected_without_local_files(auth, monkeypatch):
    org_id = auth[1]["orgs"][0]["id"]
    monkeypatch.setattr(settings, "storage_backend", "supabase")
    async with session_scope() as s:
        folder = LibraryFolder(org_id=org_id, name="Cloud research", watch_enabled=True)
        s.add(folder)
        await s.flush()
        folder_id = folder.id
        s.add(LibraryEntry(folder_id=folder.id, source_key="direct-supabase-row", title="Coffee research",
            data="Typed directly into Supabase", region="*"))
    listing = AsyncMock(return_value=[{"id": "cloud-object", "name": "research.csv", "metadata": {"size": 80}}])
    download = AsyncMock(return_value=b"title,data,region\nCoffee survey,Uploaded to Supabase,AE\n")
    monkeypatch.setattr(supabase_storage, "list_files", listing)
    monkeypatch.setattr(supabase_storage, "get", download)
    await sync_due()
    evidence = await retrieve(org_id, None, "coffee research", [{"region": "AE", "language": "English"}])
    assert {e["summary"] for e in evidence[0]} == {"Typed directly into Supabase", "Uploaded to Supabase"}
    assert listing.call_args.args[0] == f"library-inbox/{org_id}/{folder_id}"
    async with session_scope() as s:
        entries = (await s.execute(select(LibraryEntry).where(LibraryEntry.folder_id == folder_id))).scalars().all()
        assert len(entries) == 2


async def test_cloud_job_is_persisted_authenticated_and_delivered_once(client, monkeypatch):
    monkeypatch.setattr(settings, "cron_secret", "test-scheduler-secret")
    dispatch = AsyncMock()
    monkeypatch.setattr(cloud_jobs, "dispatch", dispatch)
    job_id = await cloud_jobs.enqueue("resume_autopilot", 0, {"sim_id": "fixture"})
    assert dispatch.await_count == 1
    assert (await client.post(f"/internal/jobs/{job_id}", json={})).status_code == 401
    from app.workers import tasks
    handler = AsyncMock()
    monkeypatch.setattr(tasks, "resume_autopilot", handler)
    headers = {"Authorization": "Bearer test-scheduler-secret"}
    assert (await client.post(f"/internal/jobs/{job_id}", headers=headers, json={})).json()["status"] == "done"
    assert (await client.post(f"/internal/jobs/{job_id}", headers=headers, json={})).json()["status"] == "skipped"
    assert handler.await_count == 1
    async with session_scope() as s:
        job = await s.get(CloudJob, job_id)
        assert job.status == "done" and job.attempts == 1


async def test_hosted_folder_defaults_to_cloud_and_hides_local_path(client, auth, monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "supabase")
    monkeypatch.setattr(settings, "supabase_url", "https://fixture.supabase.co")
    response = await client.post("/library/folders", headers=auth[0], json={"name": "Cloud folder"})
    assert response.status_code == 200
    folder = response.json()
    assert folder["watch_enabled"] is True
    assert folder["inbox_path"].startswith("kruvim-data/library-inbox/")
    assert folder["supabase_url"].startswith("https://supabase.com/dashboard/project/fixture/")
