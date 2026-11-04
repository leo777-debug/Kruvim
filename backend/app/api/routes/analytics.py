"""Private file-first creator analytics. All workspace data requires org membership."""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, get_sim, principal, role
from app.core.config import settings
from app.core.errors import AppError, Conflict, NotFound
from app.db.base import new_id
from app.db.session import get_session
from app.models import AnalyticsImport, AnalyticsMappingPreset, ImportedAnalyticsPost, Organization, PerformanceReport
from app.services import analytics_import as service
from app.services import audit, storage
from app.services.lifecycle import _start_locks

router = APIRouter(tags=['analytics imports'])
Platform = Literal['tiktok', 'instagram', 'youtube']
Kind = Literal['posts', 'audience']


async def mutation_guard(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    # Serialize upload/apply/delete in SQLite, and across API replicas on Postgres.
    # In particular, deleting files and rows must not race another upload.
    async with _start_locks[p.org_id]:
        await s.execute(select(Organization).where(Organization.id == p.org_id)
            .execution_options(populate_existing=True).with_for_update())
        yield


class MappingIn(BaseModel):
    columns: dict[str, str] = Field(max_length=30)
    dimension: Literal['countries', 'cities', 'ages', 'genders', 'active_hours'] | None = None
    audience_unit: Literal['percent', 'count'] = 'percent'
    complete_distribution: bool = False
    category_map: dict[str, str] = Field(default_factory=dict, max_length=500)
    date_format: str = Field(default='iso', max_length=50)
    timezone: str = Field(default='UTC', max_length=60)
    percentage_unit: Literal['percent', 'fraction'] = 'percent'
    format: str = Field(default='unknown', max_length=40)
    reported_window: str = Field(default='unspecified', max_length=120)
    preset_name: str | None = Field(default=None, min_length=1, max_length=120)


class ManualPostIn(BaseModel):
    platform: Platform
    published_at: datetime
    caption: str = Field(default='', max_length=60000)
    format: str = Field(default='unknown', max_length=40)
    metrics: dict[str, float] = Field(max_length=9)
    aggregate_only: Literal[True]


class LinkIn(BaseModel):
    simulation_id: str | None = None
    variant: Literal['A', 'B'] = 'A'


class DeleteIn(BaseModel):
    confirmed: Literal[True]


def public_import(row):
    return {'id': row.id, 'platform': row.platform, 'kind': row.kind, 'filename': row.filename,
        'created_at': row.created_at, 'status': row.status, 'mapping': row.mapping, 'summary': row.summary}


async def own_post(s, org_id, post_id):
    post = (await s.execute(select(ImportedAnalyticsPost).where(ImportedAnalyticsPost.org_id == org_id,
        ImportedAnalyticsPost.id == post_id).with_for_update())).scalar_one_or_none()
    if not post:
        raise NotFound('Imported post not found in this workspace')
    return post


@router.get('/analytics/formats')
async def formats(_: Principal = Depends(principal)):
    return {'platforms': [{'platform': platform, 'adapter': 'generic_mapper', 'verified_real_sample': False,
        'note': 'No real export sample has been verified. Preview and map your file; save the mapping for reuse.'}
        for platform in ('tiktok', 'instagram', 'youtube')], 'post_fields': service.POST_FIELDS,
        'audience_dimensions': service.DIMENSIONS, 'oauth_enabled': settings.analytics_oauth_enabled}


@router.get('/analytics/imports')
async def imports(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(AnalyticsImport).where(AnalyticsImport.org_id == p.org_id)
        .order_by(AnalyticsImport.created_at.desc()))).scalars().all()
    return [public_import(row) for row in rows]


@router.get('/analytics/presets')
async def presets(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(AnalyticsMappingPreset).where(AnalyticsMappingPreset.org_id == p.org_id))).scalars().all()
    return [{'id': row.id, 'name': row.name, 'platform': row.platform, 'kind': row.kind, 'mapping': row.mapping} for row in rows]


@router.post('/analytics/imports', dependencies=[Depends(mutation_guard)])
async def upload(platform: Platform = Form(...), kind: Kind = Form(...), aggregate_only: bool = Form(False),
    file: UploadFile = File(...), p: Principal = Depends(role('member')), s: AsyncSession = Depends(get_session)):
    if not aggregate_only:
        raise AppError('Confirm that this is your own aggregate analytics, without follower identities or individual comments.')
    filename = (file.filename or 'analytics.csv')[:240]
    if not filename.lower().endswith(('.csv', '.xlsx')):
        raise AppError('Upload a CSV or XLSX analytics file')
    raw = await file.read(25 * 1024 * 1024 + 1)
    try:
        headers, rows = service.inspect_file(raw, filename)
    except (ValueError, OSError) as exc:
        raise AppError(str(exc)) from exc
    row = AnalyticsImport(org_id=p.org_id, platform=platform, kind=kind, filename=filename,
        storage_key=f'{p.org_id}/analytics/{new_id()}', summary={'row_count': len(rows)})
    await storage.put(row.storage_key, raw)
    s.add(row)
    audit.record(s, 'analytics.upload', org_id=p.org_id, user_id=p.user_id, target=filename, meta={'platform': platform, 'rows': len(rows)})
    try:
        await s.commit()
    except Exception:
        await storage.delete(row.storage_key)
        raise
    return {**public_import(row), 'columns': headers, 'preview': rows[:5]}


@router.put('/analytics/imports/{import_id}/mapping', dependencies=[Depends(mutation_guard)])
async def mapping(import_id: str, body: MappingIn, p: Principal = Depends(role('member')), s: AsyncSession = Depends(get_session)):
    row = await service.own_import(s, p.org_id, import_id)
    if row.status != 'preview':
        raise Conflict('This import has already been applied; upload a new file to change it')
    mapped = body.model_dump(exclude={'preset_name'}, exclude_none=True)
    try:
        parsed = service.parse(await storage.get(row.storage_key), row.filename, row.kind, mapped)
    except (ValueError, KeyError, TypeError) as exc:
        raise AppError(str(exc)) from exc
    row.mapping = mapped
    if body.preset_name:
        preset = (await s.execute(select(AnalyticsMappingPreset).where(AnalyticsMappingPreset.org_id == p.org_id,
            AnalyticsMappingPreset.name == body.preset_name))).scalar_one_or_none()
        if not preset:
            preset = AnalyticsMappingPreset(org_id=p.org_id, name=body.preset_name, platform=row.platform, kind=row.kind)
            s.add(preset)
        preset.mapping, preset.platform, preset.kind = mapped, row.platform, row.kind
    await s.commit()
    return {'summary': {key: value for key, value in parsed.items() if key != 'posts'}, 'posts_preview': parsed.get('posts', [])[:5]}


@router.post('/analytics/imports/{import_id}/apply', dependencies=[Depends(mutation_guard)])
async def apply(import_id: str, p: Principal = Depends(role('member')), s: AsyncSession = Depends(get_session)):
    row = await service.own_import(s, p.org_id, import_id)
    if row.status == 'applied':
        return public_import(row)
    if not row.mapping:
        raise AppError('Map and preview the columns before applying')
    try:
        parsed = service.parse(await storage.get(row.storage_key), row.filename, row.kind, row.mapping)
    except (ValueError, KeyError, TypeError) as exc:
        raise AppError(str(exc)) from exc
    await service.apply(s, row, parsed)
    audit.record(s, 'analytics.apply', org_id=p.org_id, user_id=p.user_id, target=row.id, meta={'platform': row.platform})
    await s.commit()
    return public_import(row)


@router.post('/analytics/manual', dependencies=[Depends(mutation_guard)])
async def manual(body: ManualPostIn, p: Principal = Depends(role('member')), s: AsyncSession = Depends(get_session)):
    import csv
    import io
    if set(body.metrics) - set(service.METRICS):
        raise AppError('Choose supported aggregate metrics')
    raw = io.StringIO()
    writer = csv.DictWriter(raw, fieldnames=['published_at', 'caption', 'format', *body.metrics])
    writer.writeheader()
    writer.writerow({'published_at': body.published_at.isoformat(), 'caption': body.caption, 'format': body.format, **body.metrics})
    try:
        parsed = service.parse(raw.getvalue().encode(), 'manual.csv', 'posts', {'columns': {key: key for key in writer.fieldnames}})
    except ValueError as exc:
        raise AppError(str(exc)) from exc
    row = AnalyticsImport(org_id=p.org_id, platform=body.platform, kind='posts', filename='Manual entry')
    s.add(row)
    await s.flush()
    await service.apply(s, row, parsed)
    audit.record(s, 'analytics.manual', org_id=p.org_id, user_id=p.user_id, target=row.id)
    await s.commit()
    return public_import(row)


@router.get('/analytics/summary')
async def summary(platform: Platform | None = None, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    return await service.summary(s, p.org_id, platform)


@router.get('/analytics/posts')
async def posts(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(ImportedAnalyticsPost).where(ImportedAnalyticsPost.org_id == p.org_id)
        .order_by(ImportedAnalyticsPost.published_at.desc()).limit(200))).scalars().all()
    return [{'id': row.id, 'platform': row.platform, 'published_at': row.published_at, 'caption': row.caption,
        'format': row.format, 'metrics': row.metrics, 'simulation_id': row.simulation_id, 'variant': row.variant} for row in rows]


@router.get('/analytics/posts/{post_id}/suggestions')
async def suggestions(post_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    return await service.suggestions(s, p.org_id, await own_post(s, p.org_id, post_id))


@router.put('/analytics/posts/{post_id}/link', dependencies=[Depends(mutation_guard)])
async def link(post_id: str, body: LinkIn, p: Principal = Depends(role('member')), s: AsyncSession = Depends(get_session)):
    post = await own_post(s, p.org_id, post_id)
    if not body.simulation_id:
        report = (await s.execute(select(PerformanceReport).where(PerformanceReport.org_id == p.org_id,
            PerformanceReport.analytics_post_id == post.id))).scalar_one_or_none()
        if report:
            await s.delete(report)
        post.simulation_id, post.prediction = None, {}
    else:
        sim = await get_sim(s, p, body.simulation_id)
        if sim.status != 'completed' or not sim.results.get('score'):
            raise AppError('Link to a completed test with results')
        if sim.content.get('platform') != post.platform:
            raise AppError('Choose a test on the same platform')
        if body.variant == 'B' and not sim.content.get('variant_b'):
            raise AppError('This test has no variant B')
        post.simulation_id, post.variant, post.prediction = sim.id, body.variant, service.prediction(sim, body.variant)
        await service.outcome(s, post)
    audit.record(s, 'analytics.link', org_id=p.org_id, user_id=p.user_id, target=post.id)
    await s.commit()
    return {'ok': True, 'simulation_id': post.simulation_id}


@router.post('/analytics/delete', dependencies=[Depends(mutation_guard)])
async def delete_imports(body: DeleteIn, p: Principal = Depends(role('admin')), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(AnalyticsImport).where(AnalyticsImport.org_id == p.org_id))).scalars().all()
    for row in rows:
        if row.storage_key:
            await storage.delete(row.storage_key)
    org = (await s.execute(select(Organization).where(Organization.id == p.org_id).with_for_update())).scalar_one()
    await service.remove_all(s, org)
    audit.record(s, 'analytics.delete', org_id=p.org_id, user_id=p.user_id, target='all', meta={'imports': len(rows)})
    await s.commit()
    return {'deleted_imports': len(rows)}
