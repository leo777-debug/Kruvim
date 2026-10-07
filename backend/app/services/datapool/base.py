"""Connector framework. A connector turns one external source into normalised Signals."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import httpx

UA = {"User-Agent": "Kruvim/1.0 (+https://kruvim.app; synthetic-audience research)"}


@dataclass
class ConnectorSpec:
    key: str
    name: str
    category: str                  # weather | news | tone | attention | events | social | economy
    description: str
    secrets: list[str] = field(default_factory=list)    # names of required credentials (empty = keyless)
    interval_minutes: int = 60
    supports_search: bool = False  # can look up live posts about a topic (social listening)
    license_note: str = ""
    docs_url: str = ""


@dataclass
class SignalItem:
    kind: str
    region: str
    title: str
    value: float | None = None
    url: str | None = None
    lang: str | None = None
    observed_at: datetime | None = None
    payload: dict = field(default_factory=dict)


class MissingCredentials(Exception):
    pass


class BaseConnector:
    spec: ConnectorSpec

    def need(self, secrets: dict) -> None:
        missing = [k for k in self.spec.secrets if not secrets.get(k)]
        if missing:
            raise MissingCredentials("Missing credentials: " + ", ".join(missing))

    async def fetch(self, client: httpx.AsyncClient, regions: list[dict], secrets: dict, config: dict) -> list[SignalItem]:
        raise NotImplementedError

    async def search(self, client: httpx.AsyncClient, query: str, regions: list[dict], secrets: dict, config: dict,
                     limit: int = 10) -> list[SignalItem]:
        return []
