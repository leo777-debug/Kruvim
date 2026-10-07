"""Bounded public-page imports using the existing redirect and address checks."""
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from app.core.errors import AppError
from app.services.monitoring import fetch


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.title = False
        self.title_text, self.parts = [], []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.hidden += 1
        if tag == 'title':
            self.title = True

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.hidden = max(0, self.hidden - 1)
        if tag == 'title':
            self.title = False

    def handle_data(self, data):
        if not self.hidden and data.strip():
            (self.title_text if self.title else self.parts).append(data.strip())


async def import_link(url):
    host = (urlparse(url).hostname or '').lower().removeprefix('www.')
    if any(host == domain or host.endswith('.' + domain) for domain in ('youtube.com', 'youtu.be', 'tiktok.com', 'instagram.com')):
        raise AppError('For this video platform, upload the file or paste its script. A public post link does not provide the video or transcript.')
    try:
        data = await fetch(url)
    except httpx.HTTPError as exc:
        raise AppError('The page could not be read. Paste the content or upload it instead.') from exc
    if data.startswith(b'%PDF'):
        from . import document_text
        text, title = document_text(data, 'link.pdf'), 'Imported document'
    else:
        parser = PageText()
        parser.feed(data.decode('utf-8', errors='replace'))
        text, title = '\n'.join(parser.parts), ' '.join(parser.title_text)
    if not text.strip():
        raise AppError('The page has no readable public text. Paste the content or upload it instead.')
    return {'title': title[:300], 'text': text[:60000], 'source_url': url,
            'note': 'Only public page text was imported. Review it before testing; images, audio and video were not read.'}
