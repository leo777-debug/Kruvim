import pytest

from app.core.errors import AppError
from app.services.content import links


async def test_link_text_excludes_scripts_and_preserves_provenance(monkeypatch):
    async def fetch(url):
        return b'<html><title>My article</title><script>private tracking code</script><p>Useful article content.</p></html>'
    monkeypatch.setattr(links, 'fetch', fetch)
    out = await links.import_link('https://example.com/article')
    assert out['text'] == 'Useful article content.'
    assert out['title'] == 'My article' and out['source_url'] == 'https://example.com/article'
    with pytest.raises(AppError, match='upload the file'):
        await links.import_link('https://www.youtube.com/watch?v=example')


async def test_link_import_is_workspace_scoped(client, auth, monkeypatch):
    h, _ = auth
    project = (await client.post('/projects', headers=h, json={'name': 'Links'})).json()
    async def fetch(url):
        return b'<p>A helpful article.</p>'
    monkeypatch.setattr(links, 'fetch', fetch)
    response = await client.post(f"/projects/{project['id']}/import-link", headers=h, json={'url': 'https://example.com/article'})
    assert response.status_code == 200 and response.json()['text'] == 'A helpful article.'
    other = (await client.post('/auth/register', json={'email': 'links@example.com', 'password': 'long-disposable-password', 'name': 'Other', 'org_name': 'Other'})).json()
    headers = {'Authorization': 'Bearer ' + other['access_token']}
    assert (await client.post(f"/projects/{project['id']}/import-link", headers=headers, json={'url': 'https://example.com/article'})).status_code == 404
