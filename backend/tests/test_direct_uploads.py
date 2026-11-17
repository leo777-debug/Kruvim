from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.services import storage


async def setup(client, auth, monkeypatch, size=6_000_000):
    h, _ = auth
    pid = (await client.post('/projects', headers=h, json={'name': 'Uploads'})).json()['id']
    monkeypatch.setattr(settings, 'storage_backend', 'supabase')
    monkeypatch.setattr(storage, 'signed_upload', AsyncMock(return_value={
        'url': 'https://storage.example/upload', 'method': 'PUT', 'headers': {'Content-Type': 'video/mp4'}}))
    response = await client.post(f'/projects/{pid}/assets/upload', headers=h,
        json={'filename': 'video.mp4', 'mime': 'video/mp4', 'size': size})
    assert response.status_code == 200, response.text
    return h, pid, response.json()


async def test_large_upload_finalization_is_verified_and_idempotent(client, auth, monkeypatch):
    size = 500 * 1024 * 1024
    h, pid, target = await setup(client, auth, monkeypatch, size)
    assert target['transport'] == 'direct' and target['method'] == 'PUT'
    info = AsyncMock(return_value={'size': size, 'mime': 'video/mp4'})
    monkeypatch.setattr(storage, 'info', info)
    download = AsyncMock(side_effect=AssertionError('Media must not download at finalization'))
    monkeypatch.setattr(storage, 'get', download)
    first = await client.post(f'/projects/{pid}/assets/complete', headers=h, json={'ticket': target['ticket']})
    assert first.status_code == 200, first.text
    assert first.json()['size'] == size
    again = await client.post(f'/projects/{pid}/assets/complete', headers=h, json={'ticket': target['ticket']})
    assert again.json()['id'] == first.json()['id']
    assert info.await_count == 1
    download.assert_not_awaited()
    assert len((await client.get(f'/projects/{pid}', headers=h)).json()['assets']) == 1


async def test_upload_limits_and_project_bound_authorization(client, auth, monkeypatch):
    h, pid, target = await setup(client, auth, monkeypatch)
    for body, status in [({'size': 501 * 1024 * 1024, 'mime': 'video/mp4'}, 413),
                         ({'size': 12, 'mime': 'application/x-executable'}, 415)]:
        response = await client.post(f'/projects/{pid}/assets/upload', headers=h, json={'filename': 'a.bin', **body})
        assert response.status_code == status, response.text
    other = (await client.post('/projects', headers=h, json={'name': 'Other'})).json()['id']
    info = AsyncMock()
    monkeypatch.setattr(storage, 'info', info)
    for project, ticket in [(other, target['ticket']), (pid, 'invalid')]:
        response = await client.post(f'/projects/{project}/assets/complete', headers=h, json={'ticket': ticket})
        assert response.status_code == 403, response.text
    info.assert_not_awaited()


@pytest.mark.parametrize('actual', [{'size': 9, 'mime': 'video/mp4'}, {'size': 6_000_000, 'mime': 'text/plain'}])
async def test_completion_rejects_storage_mismatch(client, auth, monkeypatch, actual):
    h, pid, target = await setup(client, auth, monkeypatch)
    monkeypatch.setattr(storage, 'info', AsyncMock(return_value=actual))
    response = await client.post(f'/projects/{pid}/assets/complete', headers=h, json={'ticket': target['ticket']})
    assert response.status_code == 422, response.text
    assert (await client.get(f'/projects/{pid}', headers=h)).json()['assets'] == []


async def test_local_fallback_and_hosted_guard(client, auth, monkeypatch):
    h, _ = auth
    pid = (await client.post('/projects', headers=h, json={'name': 'Local'})).json()['id']
    response = await client.post(f'/projects/{pid}/assets/upload', headers=h,
        json={'filename': 'brief.md', 'mime': 'text/markdown', 'size': 5, 'kind': 'seed'})
    assert response.json()['transport'] == 'local'
    response = await client.post(f'/projects/{pid}/assets', headers=h, data={'kind': 'seed'},
        files={'file': ('brief.md', b'hello', 'text/markdown')})
    assert response.status_code == 200 and response.json()['excerpt'] == 'hello'
    monkeypatch.setattr(settings, 'serverless', True)
    response = await client.post(f'/projects/{pid}/assets', headers=h,
        files={'file': ('brief.md', b'hello', 'text/markdown')})
    assert response.status_code == 400
    assert (await client.get(f'/projects/{pid}', headers=h)).status_code == 200


async def test_supabase_storage_protocol(monkeypatch):
    import httpx

    from app.services import supabase_storage as cloud
    monkeypatch.setattr(settings, 'supabase_url', 'https://project.supabase.co')
    request = AsyncMock(side_effect=[httpx.Response(200, json={'file_size_limit': 524288000}),
        httpx.Response(200, json={'url': '/object/upload/sign/bucket/a?token=scoped'}),
        httpx.Response(200, json={'metadata': {'size': 6_000_000, 'mimetype': 'video/mp4'}})])
    monkeypatch.setattr(cloud, 'request', request)
    target = await cloud.signed_upload('org/project/a.mp4', 'video/mp4', 6_000_000)
    assert target['url'] == 'https://project.supabase.co/storage/v1/object/upload/sign/bucket/a?token=scoped'
    assert target['headers'] == {'Content-Type': 'video/mp4', 'x-upsert': 'false'}
    assert await cloud.info('org/project/a.mp4') == {'size': 6_000_000, 'mime': 'video/mp4'}


async def test_bucket_limit_rejected_before_signing(monkeypatch):
    import httpx

    from app.core.errors import AppError
    from app.services import supabase_storage as cloud
    request = AsyncMock(return_value=httpx.Response(200, json={'file_size_limit': 50 * 1024 * 1024}))
    monkeypatch.setattr(cloud, 'request', request)
    with pytest.raises(AppError, match='50 MB'):
        await cloud.signed_upload('org/project/a.mp4', 'video/mp4', 51 * 1024 * 1024)
    assert request.await_count == 1


async def test_direct_document_excerpt(client, auth, monkeypatch):
    h, pid, _ = await setup(client, auth, monkeypatch)
    raw = b'# Research\nPrivate evidence.'
    start = await client.post(f'/projects/{pid}/assets/upload', headers=h,
        json={'filename': 'research.md', 'mime': 'text/markdown', 'kind': 'seed', 'size': len(raw)})
    monkeypatch.setattr(storage, 'info', AsyncMock(return_value={'size': len(raw), 'mime': 'text/markdown'}))
    monkeypatch.setattr(storage, 'get', AsyncMock(return_value=raw))
    result = await client.post(f'/projects/{pid}/assets/complete', headers=h, json={'ticket': start.json()['ticket']})
    assert result.status_code == 200, result.text
    assert result.json()['excerpt'] == raw.decode()
