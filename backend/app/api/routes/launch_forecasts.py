"""Launch forecasts: test an announcement before release, lock the prediction, score it against the real reaction after
release, and keep a running accuracy record across companies."""
from datetime import date, datetime

import numpy as np
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, get_sim, principal, role
from app.api.routes.platform import _spearman
from app.core.errors import AppError, Conflict, NotFound
from app.db.base import utcnow
from app.db.session import get_session
from app.models import LaunchForecast
from app.services import audit
from app.services import launch_forecast as service

router = APIRouter(tags=['launch forecasts'])
CONTAMINATION = ('Language models already know how launches before their training cutoff were received, so backtests on those '
                 'launches are contaminated. Only launches announced after the model\'s training cutoff, locked before release, '
                 'count toward the accuracy record.')


class SourcesIn(BaseModel):
    youtube_video_ids: list[str] = Field(default_factory=list, max_length=20)
    reddit_query: str = Field(default='', max_length=200)
    window_days: int = Field(default=14, ge=1, le=90)
    background_video_ids: list[str] = Field(default_factory=list, max_length=20)
    background_reddit_query: str = Field(default='', max_length=200)


class ForecastIn(BaseModel):
    company: str = Field(min_length=1, max_length=120)
    product: str = Field(min_length=1, max_length=200)
    announcement_date: date
    release_date: date
    context_cutoff: datetime | None = None
    model_knowledge_cutoff: date | None = None
    simulation_id: str | None = None
    previous_id: str | None = None
    sources: SourcesIn = Field(default_factory=SourcesIn)
    notes: str = Field(default='', max_length=4000)

    @model_validator(mode='after')
    def ordered(self):
        if self.release_date < self.announcement_date:
            raise ValueError('The release date cannot be before the announcement date.')
        return self


class ForecastPatch(BaseModel):
    company: str | None = Field(default=None, min_length=1, max_length=120)
    product: str | None = Field(default=None, min_length=1, max_length=200)
    announcement_date: date | None = None
    release_date: date | None = None
    context_cutoff: datetime | None = None
    model_knowledge_cutoff: date | None = None
    simulation_id: str | None = None
    previous_id: str | None = None
    sources: SourcesIn | None = None
    notes: str | None = Field(default=None, max_length=4000)


async def own(s, org_id, forecast_id, lock=False) -> LaunchForecast:
    q = select(LaunchForecast).where(LaunchForecast.org_id == org_id, LaunchForecast.id == forecast_id)
    f = (await s.execute(q.with_for_update().execution_options(populate_existing=True) if lock else q)).scalar_one_or_none()
    if not f:
        raise NotFound('Launch forecast not found in this workspace.')
    return f


async def rows_of(s, org_id) -> list[LaunchForecast]:
    return list((await s.execute(select(LaunchForecast).where(LaunchForecast.org_id == org_id)
                                 .order_by(LaunchForecast.release_date.desc(), LaunchForecast.created_at.desc()))).scalars())


def public(f: LaunchForecast, rows: list[LaunchForecast]) -> dict:
    reasons = service.eligibility(f)
    return {'id': f.id, 'company': f.company, 'product': f.product, 'announcement_date': f.announcement_date,
            'release_date': f.release_date, 'context_cutoff': f.context_cutoff, 'model_knowledge_cutoff': f.model_knowledge_cutoff,
            'simulation_id': f.simulation_id, 'previous_id': f.previous_id, 'sources': f.sources, 'notes': f.notes,
            'background': {k: v for k, v in (f.background or {}).items() if k != 'items'} or None,
            'prediction': f.prediction or None, 'prediction_hash': f.prediction_hash, 'locked_at': f.locked_at,
            'hash_valid': service.digest(f) == f.prediction_hash if f.locked_at else None,
            'outcome': f.outcome or None, 'scored_at': f.scored_at, 'status': service.status(f),
            'comparison': service.compare(f, service.previous_of(f, rows)),
            'counts_toward_record': not reasons, 'excluded_because': reasons, 'created_at': f.created_at}


async def check_links(s, p: Principal, f: LaunchForecast):
    if f.simulation_id:
        await get_sim(s, p, f.simulation_id)
    if f.previous_id:
        if f.previous_id == f.id:
            raise AppError('A launch cannot be its own previous launch.')
        await own(s, p.org_id, f.previous_id)


@router.get('/launch-forecasts')
async def list_forecasts(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    rows = await rows_of(s, p.org_id)
    return [public(f, rows) for f in rows]


@router.post('/launch-forecasts')
async def create(body: ForecastIn, p: Principal = Depends(role('member')), s: AsyncSession = Depends(get_session)):
    data = body.model_dump()
    data['context_cutoff'] = data['context_cutoff'] or service.cutoff_for(body.announcement_date)
    f = LaunchForecast(org_id=p.org_id, created_by=p.user_id, **data)
    await check_links(s, p, f)
    s.add(f)
    audit.record(s, 'launch_forecast.create', org_id=p.org_id, user_id=p.user_id, target=f.company, meta={'product': f.product})
    await s.commit()
    return public(f, await rows_of(s, p.org_id))


@router.get('/launch-forecasts/scoreboard')
async def scoreboard(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    rows = await rows_of(s, p.org_id)
    items = [public(f, rows) for f in rows]

    def summary(group):
        scored = [i for i in group if i['comparison']]
        directions = [i['comparison']['direction']['correct'] for i in scored if i['comparison']['direction']]
        pairs = [(i['prediction']['score'], i['outcome']['score']) for i in scored]
        return {'n': len(scored), 'companies': len({i['company'].casefold() for i in scored}),
                'mean_abs_error': round(float(np.mean([i['comparison']['abs_error'] for i in scored])), 2) if scored else None,
                'direction_n': len(directions), 'direction_hit_rate': round(sum(directions) / len(directions), 3) if directions else None,
                'spearman': _spearman(*zip(*pairs)) if len(pairs) >= 3 else None}
    by_status = {k: sum(i['status'] == k for i in items) for k in ('pending', 'locked', 'scored', 'reference')}
    return {'rows': items, 'record': summary([i for i in items if i['counts_toward_record']]), 'all': summary(items),
            'by_status': by_status, 'contamination_note': CONTAMINATION,
            'method': 'Absolute error on the 0-10 opinion scale; direction compares each launch with the same company\'s previous '
                      f'launch (changes under {service.DIRECTION_DEADBAND} points count as flat); Spearman rank correlation '
                      'needs at least 3 scored forecasts.'}


@router.get('/launch-forecasts/{forecast_id}')
async def get_forecast(forecast_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    f = await own(s, p.org_id, forecast_id)
    out = public(f, await rows_of(s, p.org_id))
    out['background'] = f.background or None
    out['locked_payload'] = service.locked_payload(f) if f.locked_at else None
    return out


@router.patch('/launch-forecasts/{forecast_id}')
async def update(forecast_id: str, body: ForecastPatch, p: Principal = Depends(role('member')), s: AsyncSession = Depends(get_session)):
    f = await own(s, p.org_id, forecast_id, lock=True)
    if f.locked_at:
        raise Conflict('This forecast is locked. Locked predictions cannot be edited.', code='forecast_locked')
    data = body.model_dump(exclude_unset=True)
    if 'announcement_date' in data and 'context_cutoff' not in data:
        data['context_cutoff'] = service.cutoff_for(data['announcement_date'])
    for key, value in data.items():
        setattr(f, key, value)
    if f.release_date < f.announcement_date:
        raise AppError('The release date cannot be before the announcement date.')
    await check_links(s, p, f)
    await s.commit()
    return public(f, await rows_of(s, p.org_id))


@router.delete('/launch-forecasts/{forecast_id}')
async def delete(forecast_id: str, p: Principal = Depends(role('member')), s: AsyncSession = Depends(get_session)):
    f = await own(s, p.org_id, forecast_id, lock=True)
    if f.locked_at:
        raise Conflict('Locked forecasts stay on the record and cannot be deleted.', code='forecast_locked')
    await s.delete(f)
    await s.commit()
    return {'ok': True}


@router.post('/launch-forecasts/{forecast_id}/lock')
async def lock(forecast_id: str, p: Principal = Depends(role('member')), s: AsyncSession = Depends(get_session)):
    f = await own(s, p.org_id, forecast_id, lock=True)
    if f.locked_at:
        raise Conflict('This forecast is already locked.', code='forecast_locked')
    if not f.simulation_id:
        raise AppError('Link a completed simulation of the announcement before locking.')
    sim = await get_sim(s, p, f.simulation_id)
    if sim.status != 'completed' or not (sim.results or {}).get('score'):
        raise AppError('The linked simulation has not completed yet.')
    at = service.context_time(sim)
    if at > f.context_cutoff:
        raise AppError(f'The simulation used context from {at.isoformat()}, after this forecast\'s cutoff '
                       f'({f.context_cutoff.isoformat()}). Re-run it with the publish time set on or before the cutoff so it only '
                       'sees data from before the announcement.', code='context_after_cutoff')
    f.prediction = service.snapshot_prediction(sim)
    f.locked_at = utcnow()
    f.prediction_hash = service.digest(f)
    audit.record(s, 'launch_forecast.lock', org_id=p.org_id, user_id=p.user_id, target=f.id, meta={'hash': f.prediction_hash})
    await s.commit()
    return public(f, await rows_of(s, p.org_id))


@router.post('/launch-forecasts/{forecast_id}/background')
async def background(forecast_id: str, p: Principal = Depends(role('member')), s: AsyncSession = Depends(get_session)):
    f = await own(s, p.org_id, forecast_id)
    if f.locked_at:
        raise Conflict('This forecast is locked; background seeds only matter before the simulation runs.', code='forecast_locked')
    result = await service.collect_background(f)
    f = await own(s, p.org_id, forecast_id, lock=True)
    if f.locked_at:
        raise Conflict('This forecast was locked meanwhile.', code='forecast_locked')
    f.background = result
    await s.commit()
    return result


@router.post('/launch-forecasts/{forecast_id}/outcome')
async def outcome(forecast_id: str, p: Principal = Depends(role('member')), s: AsyncSession = Depends(get_session)):
    f = await own(s, p.org_id, forecast_id)
    if utcnow().date() <= f.release_date:
        raise AppError(f'{f.product} is not released yet; collect the outcome from {f.release_date.isoformat()} onwards.',
                       code='not_released')
    if not f.locked_at and f.simulation_id:
        raise AppError('Lock the prediction before collecting the outcome.', code='not_locked')
    if not ((f.sources or {}).get('youtube_video_ids') or (f.sources or {}).get('reddit_query')):
        raise AppError('Add official launch or review video ids, or a Reddit search, to collect the outcome from.')
    # Release the row while collecting (network + model calls), then write the result under a fresh lock.
    await s.commit()
    result = await service.collect_outcome(f)
    if not result['n']:
        raise AppError('No post-release comments could be collected or rated. Check the sources and connector credentials.',
                       code='no_outcome', details={'collected': result['collected']})
    f = await own(s, p.org_id, forecast_id, lock=True)
    f.outcome, f.scored_at = result, utcnow()
    audit.record(s, 'launch_forecast.score', org_id=p.org_id, user_id=p.user_id, target=f.id, meta={'n': result['n']})
    await s.commit()
    return public(f, await rows_of(s, p.org_id))
