"""One shared state/action contract for the creator UI and API clients."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, get_sim, principal, role, superuser
from app.core.config import settings
from app.core.errors import AppError, NotFound, QuotaExceeded
from app.db.base import utcnow
from app.db.session import get_session
from app.models import (
    Organization,
    PlanAllowance,
    ProviderConfig,
    ProviderHealth,
    ProviderIncident,
    Simulation,
    TokenCall,
    TokenNotice,
    User,
)
from app.services import audit, quotas, token_budget
from app.services.llm import Usage, make_llm
from app.services.llm.errors import PROVIDERS, ProviderFailure, provider_name
from app.services.providers import Resolved, resolve, to_settings

router = APIRouter(tags=['tokens'])


async def key_test(res):
    llm = None
    status = 'ok'
    raw = ''
    try:
        llm = make_llm(res.settings)
        if not llm.is_dry:
            await llm.complete(system='Reply OK.', user='OK?', role='voice', max_tokens=2, json_out=False, usage=Usage())
    except ProviderFailure as exc:
        status, raw = exc.category, exc.raw
    except Exception as exc:
        status, raw = 'request_error', str(exc)
    finally:
        if llm:
            await llm.aclose()
    await token_budget.provider_status(res, status, raw)
    label = PROVIDERS.get(provider_name(res.settings), {'label': 'Model provider'})['label']
    messages = {'ok': f'Your {label} key is working.', 'quota_exhausted': f'Your {label} API key has run out of credit.',
        'invalid_key': f"Your {label} API key isn't working. Check it in Settings.",
        'rate_limited': f'{label} is receiving too many requests. Wait and try again.',
        'provider_down': f'{label} is unavailable right now. Try again later.',
        'request_error': 'Check the endpoint and model in Settings.'}
    return {'ok': status == 'ok', 'status': status, 'message': messages[status], 'checked_at': utcnow().isoformat()}


@router.get('/tokens')
async def token_state(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    org = await s.get(Organization, p.org_id, with_for_update=not settings.billing_enabled)
    state = await quotas.allowance(s, org, user_id=p.seat_user_id)
    res = await resolve(s, p.org_id)
    config = await s.get(ProviderConfig, res.config_id) if res.config_id else None
    state['issue'] = None
    if not settings.billing_enabled and res.metered and not state['available']:
        state['issue'] = quotas.exhausted(state)
    if res.metered:
        health = await s.get(ProviderHealth, res.config_id or 'env:' + provider_name(res.settings))
        if health and health.status in ('quota_exhausted', 'invalid_key'):
            state['issue'] = token_budget.provider_state(res, health.status)
    if config and config.last_status in ('quota_exhausted', 'invalid_key'):
        state['issue'] = token_budget.provider_state(res, config.last_status)
    state['metered'] = res.metered
    await s.commit()
    return state


@router.post('/tokens/remind')
async def remind(p: Principal = Depends(role('member')), s: AsyncSession = Depends(get_session)):
    org = await s.get(Organization, p.org_id, with_for_update=not settings.billing_enabled)
    state = await quotas.allowance(s, org, user_id=p.seat_user_id)
    existing = (await s.execute(select(TokenNotice).where(TokenNotice.org_id == p.org_id, TokenNotice.user_id == p.user_id,
        TokenNotice.kind == 'reset', TokenNotice.period == state['reset_at']))).scalar_one_or_none()
    if not existing:
        from datetime import datetime
        s.add(TokenNotice(org_id=p.org_id, user_id=p.user_id, kind='reset', period=state['reset_at'],
            due_at=datetime.fromisoformat(state['reset_at'])))
    await s.commit()
    return {'message': "We'll notify you in Kruvim when your allowance is available again.", 'reset_at': state['reset_at']}


@router.post('/tokens/topups/notify')
async def topup_notify(p: Principal = Depends(role('member')), s: AsyncSession = Depends(get_session)):
    existing = (await s.execute(select(TokenNotice).where(TokenNotice.org_id == p.org_id, TokenNotice.user_id == p.user_id,
        TokenNotice.kind == 'topups', TokenNotice.period == 'launch'))).scalar_one_or_none()
    if not existing:
        s.add(TokenNotice(org_id=p.org_id, user_id=p.user_id, kind='topups', period='launch'))
    await s.commit()
    return {'message': "You're on the top-up notification list."}


@router.post('/tokens/topups/checkout')
async def checkout(p: Principal = Depends(role('member')), s: AsyncSession = Depends(get_session)):
    from app.services.billing import checkout as create_checkout
    return await create_checkout(s, p, 'topup')


@router.post('/providers/{config_id}/test')
async def test_saved_key(config_id: str, p: Principal = Depends(role('admin')), s: AsyncSession = Depends(get_session)):
    config = (await s.execute(select(ProviderConfig).where(ProviderConfig.id == config_id,
        ProviderConfig.org_id == p.org_id))).scalar_one_or_none()
    if not config:
        raise NotFound('Provider not found')
    await s.close()
    return await key_test(Resolved(to_settings(config), 'org', config.id))


@router.post('/simulations/{sim_id}/tokens/resume')
async def resume_tokens(sim_id: str, p: Principal = Depends(role('member')), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    res = await resolve(s, p.org_id, platform=(sim.config or {}).get('use_platform_tokens', False),
                        simulation=True, user_id=p.seat_user_id)
    if sim.pause_state.get('code') in ('provider_quota_exhausted', 'provider_invalid_key'):
        await s.close()
        result = await key_test(res)
        if not result['ok']:
            state = token_budget.provider_state(res, result['status'])
            raise QuotaExceeded(state['message'], code=state['code'], details=state)
    else:
        await s.close()
    return await token_budget.resume(p.org_id, sim_id, user_id=p.seat_user_id)


@router.post('/simulations/{sim_id}/tokens/use-platform')
async def use_platform(sim_id: str, p: Principal = Depends(role('member')), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    res = await resolve(s, p.org_id, platform=True, simulation=True, user_id=p.seat_user_id)
    if not res.metered:
        raise AppError('Kruvim tokens are not connected to a platform model yet.')
    completed = (await s.execute(select(func.count()).select_from(TokenCall).where(TokenCall.org_id == p.org_id,
        TokenCall.simulation_id == sim.id, TokenCall.namespace.like(sim.billing_epoch + ':%'), TokenCall.status == 'done'))).scalar()
    org = await s.get(Organization, p.org_id, with_for_update=not settings.billing_enabled)
    await quotas.check_tokens(s, org, max(1, sim.credits_estimate - completed), user_id=p.seat_user_id)
    sim.config = {**(sim.config or {}), 'use_platform_tokens': True}
    audit.record(s, 'tokens.use_platform', org_id=p.org_id, user_id=p.user_id, target=sim.id)
    await s.commit()
    await s.close()
    return await token_budget.resume(p.org_id, sim_id, user_id=p.seat_user_id)


class PlanIn(BaseModel):
    daily_credits: int = Field(ge=0, le=100_000_000)


@router.get('/admin/token-plans')
async def plans(_: User = Depends(superuser), s: AsyncSession = Depends(get_session)):
    overrides = {row.plan: row.daily_credits for row in (await s.execute(select(PlanAllowance))).scalars()}
    return {name: {**value, 'daily_credits': overrides.get(name, value['daily_credits'])} for name, value in quotas.PLANS.items()}


@router.put('/admin/token-plans/{name}')
async def set_plan(name: str, body: PlanIn, user: User = Depends(superuser), s: AsyncSession = Depends(get_session)):
    if name not in quotas.PLANS:
        raise NotFound('Plan not found')
    row = await s.get(PlanAllowance, name)
    if not row:
        row = PlanAllowance(plan=name, daily_credits=body.daily_credits)
        s.add(row)
    row.daily_credits = body.daily_credits
    audit.record(s, 'admin.daily_allowance', user_id=user.id, target=name, meta=body.model_dump())
    await s.commit()
    return {'plan': name, 'daily_credits': row.daily_credits}


@router.get('/admin/token-providers')
async def platform_status(_: User = Depends(superuser), s: AsyncSession = Depends(get_session)):
    configs = (await s.execute(select(ProviderConfig).where(ProviderConfig.org_id.is_(None)))).scalars().all()
    incidents = (await s.execute(select(ProviderIncident).order_by(ProviderIncident.created_at.desc()).limit(30))).scalars().all()
    paused = (await s.execute(select(Simulation).where(Simulation.status == 'paused'))).scalars().all()
    health = (await s.execute(select(ProviderHealth))).scalars().all()
    return {'health': [{'provider_key': row.provider_key, 'provider': row.provider, 'status': row.status, 'at': row.checked_at, 'last_error': row.last_error} for row in health], 'configs': [{'id': c.id, 'name': c.name, 'preset': c.preset, 'status': c.last_status,
        'at': c.last_status_at, 'last_error': c.last_error} for c in configs],
        'incidents': [{'provider': i.provider, 'category': i.category, 'at': i.created_at, 'raw_error': i.raw_error} for i in incidents],
        'paused': [{'id': sim.id, 'org_id': sim.org_id, 'name': sim.name, 'state': sim.pause_state} for sim in paused
                   if sim.pause_state.get('code') == 'platform_provider_unavailable']}


@router.post('/admin/token-providers/test')
async def test_platform_key(_: User = Depends(superuser), s: AsyncSession = Depends(get_session)):
    res = await resolve(s, None, platform=True)
    await s.close()
    return await key_test(res)


@router.post('/admin/token-providers/resume')
async def resume_platform(_: User = Depends(superuser), s: AsyncSession = Depends(get_session)):
    result = await test_platform_key(_, s)
    if not result['ok']:
        return {**result, 'resumed': 0}
    await token_budget.tick()
    return {**result, 'message': 'Eligible paused tests have been queued to continue.'}
