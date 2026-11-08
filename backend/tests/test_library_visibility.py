import pytest
from sqlalchemy import select

from app.db.session import session_scope
from app.models import AgentMemory, Membership, SimAgent
from app.services import jobs
from app.services.library import retrieve
from tests.test_library import folder, row


async def register(client, email):
    response = await client.post('/auth/register', json={
        'email': email, 'password': 'correct-horse-battery', 'org_name': email.split('@')[0]})
    assert response.status_code == 200, response.text
    data = response.json()
    return {'Authorization': 'Bearer ' + data['access_token']}, data


async def test_public_sharing_is_explicit_read_only_and_withdrawable(client, auth):
    admin_h, _ = auth
    h, owner = await register(client, 'contributor@example.com')
    private = await folder(client, h)
    entry = await row(client, h, private['id'])
    denied = await client.put(f"/library/folders/{private['id']}", headers=h,
        json={'name': 'Research', 'visibility': 'public'})
    assert denied.status_code == 400
    assert (await client.post('/library/folders', headers=h,
        json={'name': 'Fake baseline', 'visibility': 'baseline'})).status_code == 403
    public = await folder(client, h, 'Community coffee', visibility='public', publish_confirmed=True)
    public_row = await row(client, h, public['id'])
    reader_h, _ = await register(client, 'reader@example.com')
    assert (await client.get('/library/folders', headers=reader_h)).json() == []
    listed = (await client.get('/library/folders?visibility=public', headers=reader_h)).json()
    assert len(listed) == 1 and listed[0]['id'] == public['id']
    assert listed[0]['can_edit'] is False and listed[0]['owned'] is False
    assert 'supabase_url' not in listed[0] and listed[0]['inbox_path'] is None
    assert (await client.get(f"/library/folders/{private['id']}/entries", headers=reader_h)).status_code == 404
    assert (await client.get(f"/library/folders/{public['id']}/entries", headers=reader_h)).status_code == 200
    for method, path, body in [
        ('POST', f"/library/folders/{public['id']}/entries", {'title': 'x', 'data': 'tampered'}),
        ('PUT', f"/library/folders/{public['id']}/entries/{public_row['id']}", {'title': 'x', 'data': 'tampered'}),
        ('DELETE', f"/library/folders/{public['id']}/entries/{public_row['id']}", None),
        ('PUT', f"/library/folders/{public['id']}", {'name': 'tampered', 'visibility': 'private'}),
    ]:
        response = await client.request(method, path, headers=reader_h, json=body)
        assert response.status_code == 404
    assert (await client.put(f"/library/folders/{public['id']}", headers=h,
        json={'name': public['name'], 'visibility': 'private'})).status_code == 200
    assert (await client.get('/library/folders?visibility=public', headers=reader_h)).json() == []
    assert (await client.get(f"/library/folders/{public['id']}/entries", headers=reader_h)).status_code == 404
    # No existing upload is implicitly published.
    assert len((await client.get('/library/folders', headers=h)).json()) == 2
    assert (await client.get(f"/library/folders/{private['id']}/entries", headers=h)).json()['entries'][0]['id'] == entry['id']


async def test_private_and_public_retrieval_have_distinct_pools(client, auth):
    admin_h, _ = auth
    baseline = await folder(client, admin_h, 'Admin', visibility='baseline')
    base_row = await row(client, admin_h, baseline['id'], data='Admin coffee observation')
    h, owner = await register(client, 'owner@example.net')
    private = await folder(client, h, 'Private')
    own_row = await row(client, h, private['id'], data='Private coffee observation')
    own_public = await folder(client, h, 'Own public', visibility='public', publish_confirmed=True)
    own_public_row = await row(client, h, own_public['id'], data='Own coffee observation')
    other_h, _ = await register(client, 'other@example.net')
    public = await folder(client, other_h, 'Community', visibility='public', publish_confirmed=True)
    community_row = await row(client, other_h, public['id'], data='Community coffee observation')
    hidden = await folder(client, other_h, 'Hidden')
    hidden_row = await row(client, other_h, hidden['id'], data='Private coffee secret')
    people = [{'region': 'AE', 'language': 'English'}]
    org_id = owner['orgs'][0]['id']
    concentrated = (await retrieve(org_id, None, 'coffee', people))[0]
    assert {x['id'] for x in concentrated} == {'library:' + r['id'] for r in (base_row, own_row, own_public_row)}
    broad = (await retrieve(org_id, None, 'coffee', people, mode='public'))[0]
    assert {x['provenance']['library_group'] for x in broad} == {'baseline', 'own', 'community'}
    assert 'library:' + community_row['id'] in {x['id'] for x in broad}
    assert 'library:' + hidden_row['id'] not in {x['id'] for x in broad}
    assert (await client.get('/library/folders?visibility=baseline', headers=h)).status_code == 403
    for path in ('connectors', 'signals', 'datasets', 'health'):
        assert (await client.get('/datapool/' + path, headers=h)).status_code == 403
        assert (await client.get('/datapool/' + path, headers=admin_h)).status_code == 200


@pytest.mark.parametrize('mode,expect_community', [('private', False), ('public', True)])
async def test_simulation_mode_reaches_frozen_evidence_and_clone(client, auth, mode, expect_community):
    admin_h, _ = auth
    baseline = await folder(client, admin_h, 'Baseline', visibility='baseline')
    await row(client, admin_h, baseline['id'], data='Baseline coffee data')
    community = await folder(client, admin_h, 'Community', visibility='public', publish_confirmed=True)
    await row(client, admin_h, community['id'], data='Community coffee data')
    h, _ = await register(client, 'simowner@example.com')
    own = await folder(client, h)
    await row(client, h, own['id'], data='Private coffee data')
    project = (await client.post('/projects', headers=h, json={'name': 'Cafe'})).json()
    response = await client.post(f"/projects/{project['id']}/simulations", headers=h, json={
        'library_mode': mode, 'content': {'type': 'text', 'title': 'Coffee', 'text': 'Try iced coffee in Dubai.'},
        'audience': {'regions': ['AE']}, 'overrides': {'voice': 10, 'crowd': 20, 'stakeholders': 0,
            'hours': 1, 'listening': False, 'seed': 20261108}})
    assert response.status_code == 200, response.text
    sid = response.json()['id']
    for action, status in [('graph', 'graph_ready'), ('environment', 'ready'), ('start', 'completed')]:
        assert (await client.post(f'/simulations/{sid}/{action}', headers=h)).status_code == 200
        await jobs.drain()
        state = (await client.get(f'/simulations/{sid}', headers=h)).json()
        assert state['status'] == status, state.get('error')
    assert state['report_status'] == 'done'
    assert state['config']['library_mode'] == mode
    async with session_scope() as db:
        agents = (await db.execute(select(SimAgent).where(SimAgent.simulation_id == sid))).scalars().all()
        for agent in agents:
            groups = {e['provenance']['library_group'] for e in agent.config['personal_signals'] if e['source'] == 'workspace_library'}
            assert {'baseline', 'own'} <= groups
            assert ('community' in groups) is expect_community
    clone = await client.post(f'/simulations/{sid}/clone', headers=h, json={'mode': 'rerun'})
    assert clone.status_code == 200, clone.text
    assert clone.json()['config']['library_mode'] == mode
    # Switching evidence invalidates prepared state so stale public evidence cannot run as Private.
    changed = await client.patch(f'/simulations/{sid}', headers=h, json={'library_mode': 'private' if mode == 'public' else 'public'})
    assert changed.status_code == 200 and changed.json()['status'] == 'draft'


async def test_members_share_workspace_data_but_cannot_modify_baseline(client, auth):
    admin_h, admin = auth
    baseline = await folder(client, admin_h, 'Baseline', visibility='baseline')
    base_row = await row(client, admin_h, baseline['id'])
    member_h, member = await register(client, 'member@example.com')
    org_id = admin['orgs'][0]['id']
    async with session_scope() as db:
        db.add(Membership(org_id=org_id, user_id=member['user']['id'], role='member'))
    member_h['X-Org-Id'] = org_id
    private = await folder(client, member_h, 'Team data')
    await row(client, member_h, private['id'])
    assert private['id'] in {f['id'] for f in (await client.get('/library/folders', headers=admin_h)).json()}
    denied = await client.post(f"/library/folders/{baseline['id']}/entries", headers=member_h,
        json={'title': 'x', 'data': 'tampered'})
    assert denied.status_code == 403
    assert (await client.get(f"/library/folders/{baseline['id']}/entries", headers=admin_h)).json()['entries'][0]['id'] == base_row['id']


async def test_public_experiences_do_not_carry_into_private_agent_memory(client, auth):
    from app.models import Simulation
    from app.services.agent_memory import attach_snapshot, detail_memory
    from app.services.datapool.retrieval import embed

    h, session = auth
    org_id = session['orgs'][0]['id']
    project = (await client.post('/projects', headers=h, json={'name': 'Memory modes'})).json()
    runs = {}
    for mode in ('private', 'public'):
        run = (await client.post(f"/projects/{project['id']}/simulations", headers=h,
            json={'library_mode': mode, 'content': {'text': 'Coffee study'}})).json()
        runs[mode] = run
        async with session_scope() as db:
            db.add(AgentMemory(org_id=org_id, population_ref='p:1', kind='episodic', subject='topic:coffee',
                text=mode + ' coffee experience', embedding=embed('coffee').tolist(), source_simulation_id=run['id']))
    for mode in ('private', 'public'):
        snapshot = await attach_snapshot(org_id, runs[mode]['id'], {'title': 'coffee'}, [('p:1', {})])
        texts = [m['text'] for m in snapshot['snapshots']['p:1']]
        assert texts == [mode + ' coffee experience']
        async with session_scope() as db:
            sim = await db.get(Simulation, runs[mode]['id'])
        detail = await detail_memory(sim, 'p:1', {})
        assert [m['text'] for m in detail['recalled']] == texts
        assert [m['text'] for m in detail['memories']] == texts
