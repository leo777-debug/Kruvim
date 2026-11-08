import asyncio
import json
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, get_project, principal, role
from app.core.config import settings
from app.core.errors import AppError, Forbidden, NotFound
from app.db.session import get_session
from app.models.library import LibraryEntry, LibraryFolder
from app.schemas.library import EntryIn, FolderIn
from app.services import audit
from app.services.library import MAX_BYTES, cloud_prefix, import_file, inbox_path, parse_file, sync_folder

router = APIRouter(prefix="/library", tags=["data library"])


async def own_folder(s, p, folder_id, *, read=False):
    row = (await s.execute(select(LibraryFolder).where(LibraryFolder.id == folder_id,
        or_(LibraryFolder.org_id == p.org_id,
            (LibraryFolder.visibility == "public") & LibraryFolder.enabled if read else False)))).scalar_one_or_none()
    if not row:
        raise NotFound("Folder not found in this workspace.")
    if not read and row.visibility == "baseline" and not p.is_superuser:
        raise Forbidden("Only platform administrators can change admin baseline data.")
    return row


def folder_json(row, count=0, p=None):
    cloud = settings.storage_backend == "supabase"
    ref = settings.supabase_url.removeprefix("https://").split(".")[0]
    owned = p is None or row.org_id == p.org_id
    if not owned:
        return {"id": row.id, "name": row.name, "visibility": row.visibility, "owned": False,
            "can_edit": False, "project_id": None, "enabled": row.enabled, "rows": count,
            "watch_enabled": False, "sync_status": {}, "inbox_path": None, "storage": "shared"}
    return {"id": row.id, "name": row.name, "project_id": row.project_id, "enabled": row.enabled,
        "visibility": row.visibility, "owned": True,
        "can_edit": bool(p and p.role != "viewer" and (row.visibility != "baseline" or p.is_superuser)),
        "watch_enabled": row.watch_enabled, "sync_status": row.sync_status, "rows": count,
        "storage": "supabase" if cloud else "local", "database_schema": settings.database_schema or "public",
        "supabase_url": f"https://supabase.com/dashboard/project/{ref}/editor" if cloud else None,
        "supabase_storage_url": f"https://supabase.com/dashboard/project/{ref}/storage/buckets" if cloud else None,
        "inbox_path": (settings.supabase_bucket + "/" + cloud_prefix(row) if cloud else str(inbox_path(row))) if row.watch_enabled else None}


def entry_json(row):
    return {k: getattr(row, k) for k in ("id", "title", "data", "region", "language", "tags", "filename", "revision")}


@router.get("/folders")
async def folders(visibility: Literal["private", "public", "baseline"] = "private",
                  p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    if visibility == "baseline" and not p.is_superuser:
        raise Forbidden("Admin baseline folders are managed by platform administrators.")
    visible = LibraryFolder.org_id == p.org_id
    if visibility == "public":
        visible = or_(visible, LibraryFolder.enabled.is_(True))
    rows = (await s.execute(select(LibraryFolder, func.count(LibraryEntry.id)).outerjoin(LibraryEntry)
        .where(visible, LibraryFolder.visibility == visibility).group_by(LibraryFolder.id).order_by(LibraryFolder.created_at))).all()
    return [folder_json(folder, count, p) for folder, count in rows]


def validate_visibility(body, p, previous="private"):
    if body.visibility == "baseline" and not p.is_superuser:
        raise Forbidden("Only platform administrators can provide admin baseline data.")
    if body.visibility == "public" and previous != "public" and not body.publish_confirmed:
        raise AppError("Confirm that this folder's data will be shared with all Kruvim users.")


@router.post("/folders")
async def create(body: FolderIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    validate_visibility(body, p)
    if body.project_id:
        await get_project(s, p, body.project_id)
    values = body.model_dump(exclude={"publish_confirmed"})
    if settings.storage_backend == "supabase" and "watch_enabled" not in body.model_fields_set:
        values["watch_enabled"] = True
    row = LibraryFolder(org_id=p.org_id, **values)
    s.add(row)
    await s.flush()
    if settings.storage_backend == "supabase":
        from app.services.supabase_storage import put
        await put(cloud_prefix(row) + "/.keep", b"Kruvim research inbox")
    audit.record(s, "library.folder.create", org_id=p.org_id, user_id=p.user_id, target=row.id)
    await s.commit()
    return folder_json(row, p=p)


@router.put("/folders/{folder_id}")
async def edit_folder(folder_id: str, body: FolderIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    row = await own_folder(s, p, folder_id)
    if "visibility" not in body.model_fields_set:
        body.visibility = row.visibility
    validate_visibility(body, p, row.visibility)
    if body.visibility != "private" and body.project_id:
        raise AppError("Public and admin baseline folders cannot belong to one project.")
    enable_cloud_inbox = settings.storage_backend == "supabase" and body.watch_enabled and not row.watch_enabled
    if body.project_id:
        await get_project(s, p, body.project_id)
    for key, value in body.model_dump(exclude={"publish_confirmed"}).items():
        setattr(row, key, value)
    if enable_cloud_inbox:
        from app.services.supabase_storage import put
        await put(cloud_prefix(row) + "/.keep", b"Kruvim research inbox")
    audit.record(s, "library.folder.update", org_id=p.org_id, user_id=p.user_id, target=row.id)
    await s.commit()
    return folder_json(row, p=p)


@router.get("/folders/{folder_id}/entries")
async def entries(folder_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    folder = await own_folder(s, p, folder_id, read=True)
    rows = (await s.execute(select(LibraryEntry).where(LibraryEntry.folder_id == folder_id)
        .order_by(LibraryEntry.created_at, LibraryEntry.id).limit(5001))).scalars().all()
    values = [entry_json(row) for row in rows[:5000]]
    if folder.org_id != p.org_id:
        for value in values:
            value["filename"] = "Public contribution"
    return {"entries": values, "truncated": len(rows) > 5000}


@router.post("/folders/{folder_id}/entries")
async def add_entry(folder_id: str, body: EntryIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    await own_folder(s, p, folder_id)
    row = LibraryEntry(folder_id=folder_id, source_key="manual:" + uuid.uuid4().hex, **body.model_dump())
    s.add(row)
    await s.flush()
    audit.record(s, "library.row.create", org_id=p.org_id, user_id=p.user_id, target=row.id)
    await s.commit()
    return entry_json(row)


@router.put("/folders/{folder_id}/entries/{entry_id}")
async def edit_entry(folder_id: str, entry_id: str, body: EntryIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    await own_folder(s, p, folder_id)
    row = await s.get(LibraryEntry, entry_id)
    if not row or row.folder_id != folder_id:
        raise NotFound("Row not found.")
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    row.revision += 1
    audit.record(s, "library.row.update", org_id=p.org_id, user_id=p.user_id, target=row.id)
    await s.commit()
    return entry_json(row)


@router.delete("/folders/{folder_id}/entries/{entry_id}")
async def delete_entry(folder_id: str, entry_id: str, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    await own_folder(s, p, folder_id)
    row = await s.get(LibraryEntry, entry_id)
    if not row or row.folder_id != folder_id:
        raise NotFound("Row not found.")
    await s.delete(row)
    audit.record(s, "library.row.delete", org_id=p.org_id, user_id=p.user_id, target=entry_id)
    await s.commit()
    return {"ok": True}


@router.post("/folders/{folder_id}/import")
async def upload(folder_id: str, file: UploadFile = File(...), mapping: str = Form("{}"),
                 preview: bool = Form(True), p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    folder = await own_folder(s, p, folder_id)
    raw = await file.read(MAX_BYTES + 1)
    filename = (file.filename or "data.csv").replace("\\", "/").split("/")[-1]
    if len(filename) > 240:
        raise AppError("Filename exceeds 240 characters.")
    if preview:
        headers, rows = await asyncio.to_thread(parse_file, filename, raw)
        return {"headers": headers, "sample": rows[:5], "rows": len(rows)}
    try:
        columns = json.loads(mapping)
        if not isinstance(columns, dict) or any(k not in EntryIn.model_fields or not isinstance(v, str) for k, v in columns.items()):
            raise ValueError()
    except (ValueError, TypeError):
        raise AppError("Choose valid column mappings.") from None
    count = await import_file(s, folder, filename, raw, columns)
    audit.record(s, "library.import", org_id=p.org_id, user_id=p.user_id, target=folder.id, meta={"rows": count})
    await s.commit()
    return {"rows": count}


@router.post("/folders/{folder_id}/sync")
async def sync(folder_id: str, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    folder = await own_folder(s, p, folder_id)
    if not folder.watch_enabled:
        raise AppError("Enable the server inbox for this folder first.")
    result = await sync_folder(s, folder)
    await s.commit()
    return result
