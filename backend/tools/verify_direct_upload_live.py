"""Bounded production upload smoke check. No model calls; credentials stay in memory."""
import argparse
import json
import secrets
import struct
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    report = {'base_url': base, 'started_at': datetime.now(UTC).isoformat(), 'checks': []}
    project_id = refresh = None
    headers = {}

    def check(response, status, step):
        report['checks'].append({'step': step, 'status': response.status_code, 'expected': status})
        if response.status_code != status:
            # Registration and authorization responses can contain secrets. Never dump them.
            raise RuntimeError(f'{step}: expected HTTP {status}, received {response.status_code}')
        return response

    try:
        with httpx.Client(base_url=base, timeout=120) as client, tempfile.TemporaryDirectory(prefix='kruvim-media-live-') as work:
            try:
                check(client.get('/api/v1/healthz'), 200, 'health')
                check(client.get('/api/v1/readyz'), 200, 'database readiness')
                session = check(client.post('/api/v1/auth/register', json={
                    'email': f'media-smoke-{uuid.uuid4().hex}@example.com', 'password': secrets.token_urlsafe(32),
                    'name': 'Media deployment verification', 'org_name': 'Temporary media verification'}), 200, 'ordinary user registration').json()
                refresh = session['refresh_token']
                report['test_user_id'] = session['user']['id']
                report['test_org_id'] = session['orgs'][0]['id']
                headers = {'Authorization': 'Bearer ' + session['access_token'], 'X-Org-Id': report['test_org_id']}
                project = check(client.post('/api/v1/projects', headers=headers, json={'name': 'Temporary direct upload check'}),
                                200, 'create project').json()
                project_id = project['id']
                report['test_project_id'] = project_id
                path = f'/api/v1/projects/{project_id}/assets'
                video = Path(work) / 'fixture.mp4'
                subprocess.run(['ffmpeg', '-nostdin', '-y', '-loglevel', 'error', '-f', 'lavfi', '-i',
                    'color=c=blue:s=128x128:d=2', '-c:v', 'mpeg4', str(video)], check=True, capture_output=True, timeout=30)
                raw = video.read_bytes()
                padding = 6_000_000 - len(raw)
                raw += struct.pack('>I4s', padding, b'free') + bytes(padding - 8)
                assert len(raw) == 6_000_000
                target = check(client.post(path + '/upload', headers=headers, json={
                    'filename': 'fixture.mp4', 'mime': 'video/mp4', 'size': len(raw)}), 200, 'authorize 6 MB video').json()
                assert target['transport'] == 'direct'
                assert not {'authorization', 'x-org-id'} & {key.lower() for key in target['headers']}
                with httpx.Client(timeout=120) as transfer:
                    response = transfer.request(target['method'], target['url'], headers=target['headers'], content=raw)
                check(response, 200, 'direct Supabase video transfer')
                asset = check(client.post(path + '/complete', headers=headers, json={'ticket': target['ticket']}),
                              200, 'verify and finalize video').json()
                assert asset['size'] == len(raw) and asset['mime'] == 'video/mp4'
                report['video_bytes'] = asset['size']
                duplicate = check(client.post(path + '/complete', headers=headers, json={'ticket': target['ticket']}),
                                  200, 'idempotent finalization').json()
                assert duplicate['id'] == asset['id']
                check(client.post(path + '/upload', headers=headers, json={
                    'filename': 'oversized.mp4', 'mime': 'video/mp4', 'size': 51 * 1024 * 1024}), 413, 'enforce live 50 MB bucket limit')
                check(client.post(path + '/complete', headers=headers, json={'ticket': 'invalid'}), 403, 'reject invalid authorization')
                check(client.post(path, headers=headers, files={'file': ('brief.txt', b'test', 'text/plain')}),
                      400, 'reject hosted multipart fallback')
                document = b'# Deployment check\nPrivate uploaded research.'
                target = check(client.post(path + '/upload', headers=headers, json={
                    'filename': 'research.md', 'mime': 'text/markdown', 'kind': 'seed', 'size': len(document)}),
                    200, 'authorize research document').json()
                with httpx.Client(timeout=120) as transfer:
                    response = transfer.request(target['method'], target['url'], headers=target['headers'], content=document)
                check(response, 200, 'direct document transfer')
                asset = check(client.post(path + '/complete', headers=headers, json={'ticket': target['ticket']}),
                              200, 'extract document text').json()
                assert asset['excerpt'] == document.decode()
                assets = check(client.get(f'/api/v1/projects/{project_id}', headers=headers), 200, 'read saved attachments').json()['assets']
                assert len(assets) == 2
                report['result'] = 'passed'
            finally:
                if project_id:
                    check(client.delete(f'/api/v1/projects/{project_id}', headers=headers), 200, 'delete test project and stored files')
                if refresh:
                    check(client.post('/api/v1/auth/logout', json={'refresh_token': refresh}), 200, 'revoke test session')
    except Exception as error:
        report['result'] = 'failed'
        report['failure_type'] = type(error).__name__
        # Only our own bounded errors are safe to echo; transport errors can contain signed URLs.
        if isinstance(error, RuntimeError):
            report['failure'] = str(error)
    finally:
        report['finished_at'] = datetime.now(UTC).isoformat()
        destination = Path(args.evidence)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))
    return 0 if report['result'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
