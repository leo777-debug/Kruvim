"""Transactional call receipts, recoverable pauses and tenant-scoped token notices."""
import asyncio
import hashlib
import json
import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime
from functools import wraps
from inspect import signature
from typing import get_type_hints

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.core.errors import AppError, QuotaExceeded, RateLimited
from app.db.base import new_id, utcnow
from app.db.session import session_scope
from app.models import (
    Alert,
    ChatMessage,
    Membership,
    Organization,
    ProviderConfig,
    ProviderHealth,
    ProviderIncident,
    Simulation,
    Survey,
    TokenCall,
    TokenNotice,
    User,
)
from app.services import quotas
from app.services.llm.errors import PROVIDERS, BudgetPause, ProviderFailure, provider_name

current = ContextVar('token_work', default=None)
locks = defaultdict(asyncio.Lock)
log = logging.getLogger('kruvim.tokens')


def interactive_budget(needed):
    def decorate(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            params = signature(fn).bind(*args, **kwargs).arguments
            p, s, sim_id = params['p'], params['s'], params['sim_id']
            from app.api.deps import get_sim
            sim = await get_sim(s, p, sim_id)
            from app.services.providers import resolve
            res = await resolve(s, p.org_id, platform=(sim.config or {}).get('use_platform_tokens', False))
            if res.metered:
                await quotas.check_tokens(s, await s.get(Organization, p.org_id, with_for_update=True), needed)
                await s.commit()
            target = params.get('ref', 'report')
            last = (await s.execute(select(ChatMessage.id).where(ChatMessage.simulation_id == sim_id,
                ChatMessage.target == target).order_by(ChatMessage.id.desc()).limit(1))).scalar_one_or_none()
            key = hashlib.sha256(f"{target}:{last}:{params['body'].message}".encode()).hexdigest()
            work = Work(p.org_id, sim_id, f'{sim.billing_epoch}:chat:{key}', res)
            try:
                async with scope(work):
                    return await fn(*args, **kwargs)
            except BudgetPause as exc:
                if exc.state['code'] == 'ai_rate_limited':
                    raise RateLimited(exc.state['message'], code=exc.state['code'], details=exc.state) from exc
                if exc.state['code'] == 'platform_budget_exhausted':
                    raise AppError(exc.state['message'], status=503, code=exc.state['code'], details=exc.state) from exc
                raise QuotaExceeded(exc.state['message'], code=exc.state['code'], details=exc.state) from exc
        hints = get_type_hints(fn)
        wrapper.__signature__ = signature(fn).replace(parameters=[param.replace(annotation=hints.get(param.name, param.annotation))
            for param in signature(fn).parameters.values()])
        return wrapper
    return decorate


def survey_budget(fn):
    @wraps(fn)
    async def wrapper(ctx, survey_id):
        async with session_scope() as s:
            survey = await s.get(Survey, survey_id)
            sim = await s.get(Simulation, survey.simulation_id)
        work = Work(sim.org_id, sim.id, f'{sim.billing_epoch}:survey:{survey_id}')
        try:
            async with scope(work):
                return await fn(ctx, survey_id)
        except BudgetPause as exc:
            async with session_scope() as s:
                survey = await s.get(Survey, survey_id)
                survey.status, survey.pause_state = 'paused', {**exc.state, 'stage': 'run_survey'}
    return wrapper


@asynccontextmanager
async def accounting_session():
    from app.services.watchdog import job_lease
    token = job_lease.set(None)
    try:
        async with session_scope() as session:
            yield session
    finally:
        job_lease.reset(token)


def provider_state(res, category):
    key = provider_name(res.settings)
    info = PROVIDERS.get(key, {'label': 'Model provider', 'billing_url': None})
    label = info['label']
    if res.metered:
        return {'code': 'platform_provider_unavailable', 'category': category, 'provider': key, 'reset_at': None,
            'message': "Kruvim is busy right now. Your test is paused and will continue automatically. You haven't been charged for the paused part.",
            'actions': []}
    if category == 'invalid_key':
        return {'code': 'provider_invalid_key', 'category': category, 'provider': key, 'reset_at': None,
            'message': f"Your {label} API key isn't working. Check it in Settings.",
            'actions': [{'id': 'settings', 'label': 'Open Settings', 'url': '/settings'}]}
    actions = [{'id': 'use_platform', 'label': 'Use Kruvim tokens'}, {'id': 'resume', 'label': 'Resume'}]
    if info['billing_url']:
        actions.insert(0, {'id': 'billing', 'label': f'Open {label} billing', 'url': info['billing_url']})
    return {'code': 'provider_quota_exhausted', 'category': category, 'provider': key, 'reset_at': None,
        'message': f"Your {label} API key has run out of credit. Add credit in your {label} account, switch to Kruvim tokens, or wait for your provider's limit to reset.",
        'actions': actions}


async def provider_status(res, category='ok', raw=''):
    raw = raw.replace(res.settings.api_key, '[redacted]') if res.settings.api_key else raw
    async with accounting_session() as s:
        if res.metered:
            key = res.config_id or 'env:' + provider_name(res.settings)
            insert = sqlite_insert if settings.is_sqlite else pg_insert
            values = {'provider_key': key, 'provider': provider_name(res.settings), 'status': category,
                      'checked_at': utcnow(), 'last_error': raw[:2000] or None}
            await s.execute(insert(ProviderHealth).values(**values).on_conflict_do_update(index_elements=['provider_key'], set_=values))
        if res.config_id:
            config = await s.get(ProviderConfig, res.config_id, with_for_update=True)
            if config:
                config.last_status, config.last_status_at = category, utcnow()
                config.last_error = raw[:2000] or None
        if category not in ('quota_exhausted', 'invalid_key') or not res.metered:
            return
        key = res.config_id or 'env:' + provider_name(res.settings)
        now = utcnow()
        insert = sqlite_insert if settings.is_sqlite else pg_insert
        inserted = (await s.execute(insert(ProviderIncident).values(id=new_id(), provider_key=key,
            provider=provider_name(res.settings), hour=now.strftime('%Y-%m-%dT%H'), category=category,
            raw_error=raw[:2000], created_at=now).on_conflict_do_nothing(index_elements=['provider_key', 'hour'])
            .returning(ProviderIncident.id))).scalar_one_or_none()
        if not inserted:
            return
        log.error('Platform provider unavailable: %s at %s; category=%s; detail=%s', provider_name(res.settings), now.isoformat(), category, raw[:2000])
        admins = (await s.execute(select(Membership.org_id, Membership.user_id).join(User, User.id == Membership.user_id)
            .where(User.is_superuser.is_(True), User.is_active.is_(True)))).all()
        for org_id, user_id in set(admins):
            s.add(Alert(org_id=org_id, kind='platform_key', title='Platform model key needs attention',
                body=f'{provider_name(res.settings)}: {category} at {now.isoformat()}. Open Platform admin to review paused tests.'))
            from app.services.mail import notify
            await notify(user_id, 'Platform model key needs attention', f'{provider_name(res.settings)}: {category}')


class Work:
    def __init__(self, org_id, simulation_id, namespace, res=None):
        self.org_id, self.simulation_id, self.namespace, self.res = org_id, simulation_id, namespace, res
        self.paused = None

    async def call(self, llm, fn, kwargs, operation_key=None):
        if not self.res or llm.is_dry:
            return await fn(llm, **kwargs)
        signature = {k: v for k, v in kwargs.items() if k != 'usage'}
        if operation_key:
            signature = {'operation': operation_key}
        fingerprint = hashlib.sha256(json.dumps(signature, sort_keys=True, default=str).encode()).hexdigest()
        async with locks[(self.org_id, self.namespace, fingerprint)]:
            async with locks[self.org_id]:
                async with accounting_session() as s:
                    org = await s.get(Organization, self.org_id, with_for_update=True)
                    receipt = (await s.execute(select(TokenCall).where(TokenCall.org_id == self.org_id,
                        TokenCall.namespace == self.namespace, TokenCall.fingerprint == fingerprint))).scalar_one_or_none()
                    if receipt and receipt.status == 'done':
                        u = receipt.usage
                        kwargs['usage'].add(llm.name, llm.model_for(kwargs['role']), kwargs['role'], u.get('input_tokens', 0),
                            u.get('cached_tokens', 0), u.get('output_tokens', 0), 0)
                        return decrypt(receipt.response_enc)
                    if self.paused:
                        raise BudgetPause(self.paused)
                    try:
                        allocations = await quotas.debit_call(s, org) if self.res.metered and (not receipt or receipt.status == 'failed') else (receipt.allocations if receipt else {})
                    except QuotaExceeded as exc:
                        self.paused = exc.details
                        raise BudgetPause(exc.details) from exc
                    if not receipt:
                        receipt = TokenCall(org_id=self.org_id, simulation_id=self.simulation_id, namespace=self.namespace,
                            fingerprint=fingerprint, allocations=allocations)
                        s.add(receipt)
                        await s.flush()
                    receipt.status = 'reserved'
                    receipt_id = receipt.id
            from app.services.llm import Usage
            caller_usage = kwargs['usage']
            usage = Usage()
            kwargs = {**kwargs, 'usage': usage}
            from app.services.spend_budget import LIMIT_PAUSES
            from app.services.spend_budget import call as paid_call
            try:
                response = await paid_call(llm, fn, kwargs)
            except BaseException as exc:
                if isinstance(exc, BudgetPause) and exc.state['code'] in LIMIT_PAUSES:
                    self.paused = exc.state
                async with locks[self.org_id]:
                    async with accounting_session() as s:
                        receipt = await s.get(TokenCall, receipt_id, with_for_update=True)
                        org = await s.get(Organization, self.org_id, with_for_update=True)
                        await quotas.refund_call(s, org, receipt.allocations)
                        receipt.allocations, receipt.status = {}, 'failed'
                if isinstance(exc, ProviderFailure):
                    await provider_status(self.res, exc.category, exc.raw)
                    if exc.category in ('quota_exhausted', 'invalid_key'):
                        self.paused = provider_state(self.res, exc.category)
                        raise BudgetPause(self.paused) from exc
                caller_usage.failed += usage.failed
                raise
            async with accounting_session() as s:
                receipt = await s.get(TokenCall, receipt_id, with_for_update=True)
                receipt.response_enc, receipt.status = encrypt(response), 'done'
                receipt.usage = {field: getattr(usage, field) for field in ('input_tokens', 'output_tokens', 'cached_tokens')}
                if self.res.metered and self.simulation_id:
                    await s.execute(update(Simulation).where(Simulation.id == self.simulation_id,
                        Simulation.org_id == self.org_id).values(credits_charged=Simulation.credits_charged + 1))
            if not self.paused:
                await provider_status(self.res)
            caller_usage.add(llm.name, llm.model_for(kwargs['role']), kwargs['role'], usage.input_tokens,
                usage.cached_tokens, usage.output_tokens, usage.seconds)
            return response


@asynccontextmanager
async def scope(work):
    token = current.set(work)
    try:
        yield work
    finally:
        current.reset(token)


async def pause(sim_id, state, stage):
    async with session_scope() as s:
        sim = await s.get(Simulation, sim_id)
        sim.status = 'paused'
        sim.pause_state = {**state, 'stage': stage, 'paused_at': utcnow().isoformat()}
        sim.job_deadline = None
        if stage == 'generate_report':
            sim.report_status = 'paused'
    from app.services.events import bus
    await bus.publish(sim_id, 'simulation.token_paused', state)


async def tick(now=None):
    """Local-midnight reminders and automatic resumptions; called by API and workers."""
    from app.services.spend_budget import LIMIT_PAUSES

    now = now or utcnow()
    async with accounting_session() as s:
        reminders = (await s.execute(select(TokenNotice).where(TokenNotice.kind == 'reset', TokenNotice.delivered_at.is_(None),
            TokenNotice.due_at <= now).with_for_update())).scalars().all()
        for notice in reminders:
            org = await s.get(Organization, notice.org_id, with_for_update=True)
            state = await quotas.allowance(s, org, now)
            if state['available']:
                notice.delivered_at = now
                s.add(Alert(org_id=org.id, kind='tokens_reset', title='Your tokens have reset',
                    body='Your allowance is available again. Paused tests will continue automatically.'))
                from app.services.mail import notify
                await notify(notice.user_id, 'Your tokens have reset', 'Your allowance is available again.')
        sims = (await s.execute(select(Simulation).where(Simulation.status == 'paused'))).scalars().all()
    for sim in sims:
        if not sim.pause_state:
            continue
        eligible = False
        async with accounting_session() as s:
            org = await s.get(Organization, sim.org_id, with_for_update=True)
            state = await quotas.allowance(s, org, now)
            from app.services.providers import resolve
            res = await resolve(s, sim.org_id, platform=(sim.config or {}).get('use_platform_tokens', False))
            config = await s.get(ProviderConfig, res.config_id) if res.config_id else None
            if sim.pause_state['code'] == 'workspace_tokens_exhausted':
                eligible = state['available'] > 0
            elif sim.pause_state['code'] in LIMIT_PAUSES:
                eligible = now >= datetime.fromisoformat(sim.pause_state['reset_at'])
            elif sim.pause_state['code'] in ('api_budget_exhausted', 'subscription_required', 'billing_seats_exceeded'):
                from app.services.billing import status as billing_status
                paid = await billing_status(s, org.id)
                eligible = paid['active'] and paid['available'] > 0
            elif sim.pause_state['code'] in ('billing_model_unpriced', 'billing_image_unpriced'):
                eligible = False  # An operator must fix model configuration before explicit resume.
            elif sim.pause_state['code'] == 'platform_provider_unavailable':
                health = await s.get(ProviderHealth, res.config_id or 'env:' + provider_name(res.settings))
                eligible = bool(health and health.status == 'ok')
            elif config and config.last_status == 'ok':
                eligible = True
        if eligible:
            await resume(sim.org_id, sim.id, automatic=True)
    async with accounting_session() as s:
        surveys = (await s.execute(select(Survey, Simulation).join(Simulation, Simulation.id == Survey.simulation_id)
            .where(Survey.status == 'paused', Simulation.status == 'completed'))).all()
    for survey, sim in surveys:
        if survey.pause_state.get('code') in LIMIT_PAUSES:
            if now >= datetime.fromisoformat(survey.pause_state['reset_at']):
                await resume_survey(sim.org_id, sim.id, survey.id)
            continue
        async with accounting_session() as s:
            org = await s.get(Organization, sim.org_id, with_for_update=True)
            available = (await quotas.allowance(s, org, now))['available']
            from app.services.providers import resolve
            res = await resolve(s, org.id, platform=(sim.config or {}).get('use_platform_tokens', False))
            config = await s.get(ProviderConfig, res.config_id) if res.config_id else None
        paid_resume = False
        if survey.pause_state.get('code') in ('api_budget_exhausted', 'subscription_required', 'billing_seats_exceeded'):
            from app.services.billing import status as billing_status
            async with accounting_session() as s:
                paid = await billing_status(s, org.id)
                paid_resume = paid['active'] and paid['available'] > 0
        if paid_resume or survey.pause_state.get('code') == 'workspace_tokens_exhausted' and available or config and config.last_status == 'ok':
            await resume_survey(sim.org_id, sim.id, survey.id)


async def resume_survey(org_id, sim_id, survey_id):
    from app.services import jobs
    async with locks[org_id]:
        async with accounting_session() as s:
            from app.services.billing import require_access
            await require_access(s, org_id)
            sim = (await s.execute(select(Simulation).where(Simulation.id == sim_id, Simulation.org_id == org_id))).scalar_one()
            survey = (await s.execute(select(Survey).where(Survey.id == survey_id, Survey.simulation_id == sim.id).with_for_update())).scalar_one()
            if survey.status != 'paused':
                return {'resumed': False}
            survey.status, survey.pause_state = 'queued', {}
    await jobs.enqueue('run_survey', survey_id=survey_id)
    return {'resumed': True}


async def resume(org_id, sim_id, automatic=False):
    from app.services import jobs
    async with locks[org_id]:
        async with accounting_session() as s:
            from app.services.billing import require_access
            await require_access(s, org_id)
            sim = (await s.execute(select(Simulation).where(Simulation.id == sim_id, Simulation.org_id == org_id).with_for_update())).scalar_one()
            if sim.status != 'paused' or not sim.pause_state:
                return {'resumed': False}
            stage = sim.pause_state['stage']
            from app.services.providers import resolve
            res = await resolve(s, org_id, platform=(sim.config or {}).get('use_platform_tokens', False))
            if res.metered:
                await quotas.check_tokens(s, await s.get(Organization, org_id, with_for_update=True))
            sim.pause_state = {}
            sim.status = {'build_graph': 'building_graph', 'prepare_environment': 'preparing', 'run_simulation': 'queued', 'generate_report': 'completed'}[stage]
            if stage == 'generate_report':
                sim.report_status = 'queued'
        job_id = await jobs.enqueue(stage, sim_id=sim_id)
        async with accounting_session() as s:
            sim = await s.get(Simulation, sim_id)
            sim.job_id = job_id
    return {'resumed': True}
