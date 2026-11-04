"""Exercise the deployed HTTP API and Redis worker; use only on a disposable stack."""
import argparse
import asyncio
import time
import uuid

import httpx


async def check(url):
    async with httpx.AsyncClient(base_url=url.rstrip('/') + '/api/v1', timeout=30) as client:
        account = await client.post('/auth/register', json={
            'email': f"compose-{uuid.uuid4().hex}@example.com", 'password': 'disposable-compose-password',
            'name': 'Compose check', 'org_name': 'Compose check'})
        account.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + account.json()['access_token']
        project = await client.post('/projects', json={'name': 'Worker smoke'})
        project.raise_for_status()
        response = await client.post(f"/projects/{project.json()['id']}/simulations", json={
            'content': {'type': 'video', 'format': 'short_video', 'platform': 'tiktok',
                'transcript': 'Mix oats with yogurt and a banana for a quick breakfast. Try it tomorrow.'},
            'audience': {'regions': ['SA']},
            'overrides': {'voice': 10, 'crowd': 50, 'stakeholders': 0, 'hours': 1, 'listening': False}})
        response.raise_for_status()
        sid = response.json()['id']
        response = await client.post(f'/simulations/{sid}/autopilot')
        response.raise_for_status()
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            response = await client.get(f'/simulations/{sid}')
            response.raise_for_status()
            run = response.json()
            if run['status'] == 'failed' or run['report_status'] == 'failed':
                raise RuntimeError(run.get('error') or 'Worker failed')
            if run['report_status'] == 'done':
                agents = await client.get(f'/simulations/{sid}/agents')
                agents.raise_for_status()
                report = await client.get(f'/simulations/{sid}/report')
                report.raise_for_status()
                assert agents.json() and report.json()['status'] == 'done'
                print('Compose: authenticated HTTP → Redis jobs → persisted audience, results and report passed.')
                return
            await asyncio.sleep(1)
        raise RuntimeError('Compose worker did not complete the small test within 180 seconds')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://localhost:8080')
    asyncio.run(check(parser.parse_args().url))
