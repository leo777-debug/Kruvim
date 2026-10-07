"""Private analytics imports use explicit mappings
fixture numbers are synthetic."""
import asyncio
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from openpyxl import Workbook
from sqlalchemy import create_engine, inspect, select

from app.db.session import session_scope
from app.models import AnalyticsImport, PerformanceReport, Simulation
from app.services import analytics_import as service
from app.services import storage

FIXTURES = Path(__file__).parent / 'fixtures/analytics'
POST_MAPPING = {'columns': {'published_at': 'Date', 'caption': 'Title', 'views': 'Views', 'likes': 'Likes',
    'shares': 'Shares', 'completion': 'Finished', 'avg_watch_time': 'Watch', 'format': 'Format',
    'length_seconds': 'Seconds', 'hook_style': 'Hook'}, 'reported_window': 'first 7 days'}


async def import_file(client, h, platform='tiktok', kind='posts', raw=None, mapping=None, filename='fixture.csv'):
    uploaded = await client.post('/analytics/imports', headers=h,
        data={'platform': platform, 'kind': kind, 'aggregate_only': 'true'},
        files={'file': (filename, raw or (FIXTURES / 'posts.csv').read_bytes())})
    assert uploaded.status_code == 200, uploaded.text
    record = uploaded.json()
    preview = await client.put(f"/analytics/imports/{record['id']}/mapping", headers=h, json=mapping or POST_MAPPING)
    assert preview.status_code == 200, preview.text
    applied = await client.post(f"/analytics/imports/{record['id']}/apply", headers=h)
    assert applied.status_code == 200, applied.text
    return record, preview.json(), applied.json()


@pytest.mark.parametrize('platform', ['tiktok', 'instagram', 'youtube'])
async def test_platform_generic_mapper_baseline_and_idempotence(client, auth, platform):
    h, _ = auth
    record, preview, applied = await import_file(client, h, platform, mapping=POST_MAPPING | {'preset_name': 'My export'})
    assert preview['posts_preview'][0]['metrics']['avg_watch_time'] == 12
    assert applied['summary']['inserted'] == 3
    assert (await client.post(f"/analytics/imports/{record['id']}/apply", headers=h)).json()['summary']['inserted'] == 3
    assert len((await client.get('/analytics/posts', headers=h)).json()) == 3
    summary = (await client.get('/analytics/summary', headers=h)).json()
    assert summary['platforms'][platform]['medians']['views'] == 200
    assert summary['platforms'][platform]['medians']['likes'] == 20
    assert summary['platforms'][platform]['samples']['likes'] == 2  # Missing is not zero.
    assert summary['platforms'][platform]['medians']['completion'] == 60
    assert any(p['dimension'] == 'hook_style' and p['value'] == 'demonstration' for p in summary['patterns'])
    preset = (await client.get('/analytics/presets', headers=h)).json()[0]
    _, _, duplicated = await import_file(client, h, platform, mapping=preset['mapping'])
    assert duplicated['summary']['updated'] == 3 and duplicated['summary']['inserted'] == 0
    assert len((await client.get('/analytics/posts', headers=h)).json()) == 3
    formats = (await client.get('/analytics/formats', headers=h)).json()
    assert not formats['oauth_enabled']
    assert all(p['adapter'] == 'generic_mapper' and not p['verified_real_sample'] for p in formats['platforms'])
    async with session_scope() as s:
        row = await s.get(AnalyticsImport, record['id'])
        assert await storage.get(row.storage_key) == (FIXTURES / 'posts.csv').read_bytes()


async def test_audience_auto_fill_partial_coverage_and_xlsx(client, auth):
    h, _ = auth
    mapping = {'columns': {'dimension': 'Dimension', 'category': 'Category', 'value': 'Percentage'},
        'category_map': {'United Arab Emirates': 'AE', 'Saudi Arabia': 'SA'}}
    _, _, applied = await import_file(client, h, kind='audience', raw=(FIXTURES / 'audience.csv').read_bytes(), mapping=mapping)
    assert applied['summary']['split']['countries'] == {'AE': 75, 'SA': 25}
    assert applied['summary']['audience']['active_hours']['18:00'] == 60
    profile = (await client.get('/my-audience', headers=h)).json()['profile']
    assert profile['source'] == 'analytics_import' and profile['split']['genders']['female'] == 55
    import numpy as np

    from app.services.creator import weighted_sample
    from app.services.population import get_population
    pop = await get_population()
    mask = pop.mask({'regions': ['AE', 'SA'], 'age_min': 18, 'age_max': 34})
    indices, evidence = weighted_sample(pop, mask, 100, np.random.default_rng(4), profile['split'])
    assert len(indices) == 100 and evidence['max_marginal_error_percent'] < .1
    assert evidence['coverage']['cities'] == 100
    wb = Workbook()
    ws = wb.active
    ws.append(['Date', 'Views', 'Completion'])
    ws.append([datetime(2026, 9, 5, 12), 400, .8])
    buf = io.BytesIO()
    wb.save(buf)
    _, preview, _ = await import_file(client, h, platform='youtube', raw=buf.getvalue(), filename='fixture.xlsx',
        mapping={'columns': {'published_at': 'Date', 'views': 'Views', 'completion': 'Completion'}, 'percentage_unit': 'fraction', 'timezone': 'Asia/Dubai'})
    assert preview['posts_preview'][0]['metrics']['completion'] == 80
    assert datetime.fromisoformat(preview['posts_preview'][0]['published_at']) == datetime(2026, 9, 5, 8, tzinfo=UTC)
    partial = service.parse(b'Category,Value\nAE,30\n', 'partial.csv', 'audience',
        {'columns': {'category': 'Category', 'value': 'Value'}, 'dimension': 'countries'})
    assert partial['split'] == {} and partial['coverage_gaps']


async def test_linking_calibration_deletion_and_tenant_isolation(client, auth):
    h, account = auth
    record, _, _ = await import_file(client, h, mapping=POST_MAPPING | {'preset_name': 'Delete me'})
    posts = (await client.get('/analytics/posts', headers=h)).json()
    project = (await client.post('/projects', headers=h, json={'name': 'Analytics'})).json()
    now = datetime(2026, 8, 31, tzinfo=UTC)
    async with session_scope() as s:
        sims = []
        for post in posts:
            sim = Simulation(org_id=account['orgs'][0]['id'], project_id=project['id'], created_by=account['user']['id'],
                name=post['caption'], content={'type': 'video', 'platform': 'tiktok', 'title': post['caption']},
                audience={}, status='completed', finished_at=now, results={'score': {'mean': 7},
                    'provider': {'dry': False}, 'viral': {'raw': {'mean_share_intent': .2}, 'score': 60},
                    'heatmap': {'completion': .6, 'segments': [{'retention': .8, 'start': 0, 'end': 20}]},
                    'creator_analytics': {'forecast': {'views': post['metrics']['views'] * .9}}})
            s.add(sim)
            await s.flush()
            sims.append(sim.id)
    for post, sid in zip(posts, sims, strict=True):
        candidates = (await client.get(f"/analytics/posts/{post['id']}/suggestions", headers=h)).json()
        assert candidates[0]['simulation_id'] == sid
        for _ in range(2):
            linked = await client.put(f"/analytics/posts/{post['id']}/link", headers=h, json={'simulation_id': sid})
            assert linked.status_code == 200, linked.text
    summary = (await client.get('/analytics/summary', headers=h)).json()
    assert summary['calibration']['views']['n'] == 3 and summary['calibration']['views']['mean_absolute_error'] == 10
    async with session_scope() as s:
        forecast = await service.forecast(s, account['orgs'][0]['id'], 'tiktok', .4)
        assert forecast['forecast']['views'] == 400 and forecast['forecast']['usual_multiple'] == 2
        assert len((await s.execute(select(PerformanceReport))).scalars().all()) == 3
        row = await s.get(AnalyticsImport, record['id'])
        key = row.storage_key
    other = (await client.post('/auth/register', json={'email': 'other@example.com', 'password': 'correct-horse-battery', 'name': 'Other', 'org_name': 'Other'})).json()
    oh = {'Authorization': 'Bearer ' + other['access_token']}
    assert (await client.get('/analytics/posts', headers=oh)).json() == []
    assert (await client.put(f"/analytics/imports/{record['id']}/mapping", headers=oh, json=POST_MAPPING)).status_code == 404
    assert (await client.put(f"/analytics/posts/{posts[0]['id']}/link", headers=oh, json={'simulation_id': sims[0]})).status_code == 404
    assert (await client.post('/analytics/delete', headers=oh, json={'confirmed': True})).json()['deleted_imports'] == 0
    assert await storage.get(key)
    assert (await client.post('/analytics/delete', headers=h, json={'confirmed': False})).status_code == 422
    assert (await client.post('/analytics/delete', headers=h, json={'confirmed': True})).json()['deleted_imports'] == 1
    assert (await client.get('/analytics/posts', headers=h)).json() == []
    assert (await client.get('/analytics/presets', headers=h)).json() == []
    with pytest.raises((FileNotFoundError, OSError)):
        await storage.get(key)
    async with session_scope() as s:
        assert not (await s.execute(select(PerformanceReport))).scalars().all()
        assert await s.get(Simulation, sims[0])  # Tests themselves survive deletion.


async def test_manual_privacy_units_and_accuracy_eligibility(client, auth):
    h, _ = auth
    response = await client.post('/analytics/manual', headers=h, json={'platform': 'instagram', 'published_at': '2026-09-01T00:00:00Z',
        'caption': 'Own aggregate post', 'format': 'image', 'metrics': {'views': 120, 'likes': 8}, 'aggregate_only': True})
    assert response.status_code == 200, response.text
    for raw in (b'Date,Follower username,Views\n2026-09-01,person,5\n', b'Date,Caption,Views\n2026-09-01,contact@example.com,5\n'):
        assert (await client.post('/analytics/imports', headers=h, data={'platform': 'instagram', 'kind': 'posts', 'aggregate_only': 'true'},
            files={'file': ('unsafe.csv', raw)})).status_code == 400
    for value in ('-1', 'nan', '1.5'):
        with pytest.raises(ValueError):
            service.parse(f'Date,Views\n2026-09-01,{value}\n'.encode(), 'x.csv', 'posts', {'columns': {'published_at': 'Date', 'views': 'Views'}})
    date = datetime(2026, 9, 1, tzinfo=UTC)
    p = SimpleNamespace(published_at=date, prediction={'dry': True, 'finished_at': (date - timedelta(days=1)).isoformat()})
    assert not service.comparable(p)
    p.prediction['dry'] = False
    assert service.comparable(p)
    p.prediction['finished_at'] = (date + timedelta(days=1)).isoformat()
    assert not service.comparable(p)
    sim = SimpleNamespace(finished_at=date, results={'ab': {'b': {'would_share': .3, 'completion': .5}, 'b_heatmap': [{'retention': .5}]}, 'provider': {'dry': False}})
    assert service.prediction(sim, 'B')['completion'] == 50 and service.prediction(sim, 'B')['share_intent'] == .3


async def test_analytics_migration_previous_head_empty_and_downgrade(tmp_path, monkeypatch):
    from app.core.config import settings
    root = Path(__file__).parents[1]
    for name, revisions in [('previous', ('0012', 'head', 'head')), ('empty', ('head',))]:
        db = tmp_path / f'{name}.db'
        monkeypatch.setattr(settings, 'database_url', 'sqlite+aiosqlite:///' + db.as_posix())
        cfg = Config(str(root / 'alembic.ini'))
        cfg.set_main_option('script_location', str(root / 'migrations'))
        for revision in revisions:
            await asyncio.to_thread(command.upgrade, cfg, revision)
        engine = create_engine('sqlite:///' + db.as_posix())
        try:
            assert 'analytics_imports' in inspect(engine).get_table_names()
            assert 'analytics_post_id' in {c['name'] for c in inspect(engine).get_columns('performance_reports')}
            await asyncio.to_thread(command.downgrade, cfg, '0012')
            assert 'analytics_imports' not in inspect(engine).get_table_names()
            await asyncio.to_thread(command.upgrade, cfg, 'head')
        finally:
            engine.dispose()


async def test_future_connector_is_off_and_reuses_private_import_tables(client, auth, monkeypatch):
    from app.core.config import settings
    from app.services.analytics_connectors import AggregateExport, sync
    calls = []
    class FixtureConnector:
        async def fetch(self, org_id):
            calls.append(org_id)
            return AggregateExport((FIXTURES / 'posts.csv').read_bytes(), 'fixture.csv', 'posts', POST_MAPPING)
    org_id = auth[1]['orgs'][0]['id']
    async with session_scope() as s:
        with pytest.raises(ValueError, match='not enabled'):
            await sync(s, org_id, 'youtube', FixtureConnector())
        assert calls == []
        monkeypatch.setattr(settings, 'analytics_oauth_enabled', True)
        row = await sync(s, org_id, 'youtube', FixtureConnector())
        assert row.status == 'applied' and row.summary['inserted'] == 3
    assert len((await client.get('/analytics/posts', headers=auth[0])).json()) == 3
