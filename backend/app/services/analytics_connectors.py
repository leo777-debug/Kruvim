"""Future OAuth adapters feed the same private tables as files; disabled by default.

No developer-app credentials, authorization flow or network adapter is shipped here.
An approved adapter must supply aggregate data and an explicitly verified mapping.
"""
from dataclasses import dataclass
from typing import Protocol

from app.core.config import settings
from app.db.base import new_id
from app.models import AnalyticsImport
from app.services import analytics_import, storage


@dataclass
class AggregateExport:
    raw: bytes
    filename: str
    kind: str
    mapping: dict


class AnalyticsConnector(Protocol):
    async def fetch(self, org_id: str) -> AggregateExport: ...


async def sync(s, org_id: str, platform: str, adapter: AnalyticsConnector):
    if not settings.analytics_oauth_enabled:
        raise ValueError('Automatic analytics connectors are not enabled; import a file instead')
    if platform not in ('tiktok', 'instagram', 'youtube'):
        raise ValueError('Unsupported analytics platform')
    export = await adapter.fetch(org_id)
    if export.kind not in ('posts', 'audience'):
        raise ValueError('Only aggregate posts or audience exports are accepted')
    parsed = analytics_import.parse(export.raw, export.filename, export.kind, export.mapping)
    row = AnalyticsImport(org_id=org_id, platform=platform, kind=export.kind, filename=export.filename,
        mapping=export.mapping, storage_key=f'{org_id}/analytics/{new_id()}')
    await storage.put(row.storage_key, export.raw)
    s.add(row)
    await s.flush()
    await analytics_import.apply(s, row, parsed)
    return row
