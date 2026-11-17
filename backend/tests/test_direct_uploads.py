from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.services import storage


async def test_storage_timeout_returns_safe_retryable_error(monkeypatch):
    import httpx

    from app.core.errors import AppError
    from app.services import supabase_storage as cloud
    monkeypatch.setattr(settings, 'supabase_url', 'https://storage.example')
    monkeypatch.setattr(settings, 'supabase_secret_key', 'test-server-credential')
    monkeypatch.setattr(httpx.AsyncClient, 'request', AsyncMock(side_effect=httpx.ReadTimeout('private URL and credentials')))
    with pytest.raises(AppError) as error:
        await cloud.request('GET', 'object/info/private/file')
    assert error.value.status == 503
    assert error.value.code == 'storage_unavailable'
    assert 'private' not in str(error.value)
    assert 'credential' not in str(error.value)


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


async def test_six_megabytes_cross_real_storage_http_boundary(client, auth, monkeypatch):
    """Exercise routes, storage HTTP adapter and DB together, with a local storage-protocol server."""
    import asyncio
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import httpx

    uploaded = {}
    calls = []

    class StorageServer(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, data, status=200):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            calls.append(('GET', self.path, self.headers.get('Authorization')))
            if '/bucket/' in self.path:
                self.respond({'file_size_limit': 50 * 1024 * 1024})
            else:
                key = self.path.split('/object/info/', 1)[1]
                raw, mime = uploaded[key]
                self.respond({'metadata': {'size': len(raw), 'mimetype': mime}})

        def do_POST(self):
            calls.append(('POST', self.path, self.headers.get('Authorization')))
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            signed = self.path.removeprefix('/storage/v1') + '?token=local-test-scope'
            self.respond({'url': signed})

        def do_PUT(self):
            calls.append(('PUT', self.path, self.headers.get('Authorization')))
            key = self.path.split('/object/upload/sign/', 1)[1].split('?', 1)[0]
            uploaded[key] = (self.rfile.read(int(self.headers['Content-Length'])), self.headers['Content-Type'])
            self.respond({'Key': key})

    server = ThreadingHTTPServer(('127.0.0.1', 0), StorageServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(settings, 'storage_backend', 'supabase')
    monkeypatch.setattr(settings, 'supabase_url', f'http://127.0.0.1:{server.server_port}')
    monkeypatch.setattr(settings, 'supabase_secret_key', 'local-server-only')
    try:
        h, _ = auth
        pid = (await client.post('/projects', headers=h, json={'name': 'HTTP upload'})).json()['id']
        raw = b'video fixture bytes ' * 300_000
        assert len(raw) == 6_000_000
        result = await client.post(f'/projects/{pid}/assets/upload', headers=h,
            json={'filename': 'fixture.mp4', 'mime': 'video/mp4', 'size': len(raw)})
        assert result.status_code == 200, result.text
        target = result.json()
        assert 'local-server-only' not in result.text
        async with httpx.AsyncClient() as uploader:
            response = await uploader.put(target['url'], headers=target['headers'], content=raw)
        assert response.status_code == 200
        completed = await client.post(f'/projects/{pid}/assets/complete', headers=h, json={'ticket': target['ticket']})
        assert completed.status_code == 200, completed.text
        assert completed.json()['size'] == len(raw)
        assert next(iter(uploaded.values())) == (raw, 'video/mp4')
        assert [method for method, _, _ in calls] == ['GET', 'POST', 'PUT', 'GET']
        assert calls[2][2] is None
        assert all(authorization == 'Bearer local-server-only' for method, _, authorization in calls if method != 'PUT')
        assets = (await client.get(f'/projects/{pid}', headers=h)).json()['assets']
        assert [asset['id'] for asset in assets] == [completed.json()['id']]
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=5)
