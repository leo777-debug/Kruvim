"""Outbound requests to user-supplied addresses (model providers, feeds, logos, source files).

The address is checked when the connection is opened, not before, so a host name that resolves to a public
IP during validation and a private one during the request (DNS rebinding) is still refused. Each connection
goes to the exact IP that passed the check; TLS still verifies the certificate against the host name."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpcore
import httpx

from .config import settings


class BlockedAddress(httpx.ConnectError):
    pass


def is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.split("%", 1)[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


async def resolve_public(host: str, port: int) -> list[str]:
    try:
        ipaddress.ip_address(host)
        ips = [host]
    except ValueError:
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM)
        except socket.gaierror:
            raise BlockedAddress(f"The host name {host} does not resolve.")
        ips = list(dict.fromkeys(info[4][0] for info in infos))
    if not ips or not all(is_public(ip) for ip in ips):
        raise BlockedAddress(f"{host} points to a private or internal network address, which is not allowed.")
    return ips


class _PublicOnlyBackend(httpcore.AsyncNetworkBackend):
    def __init__(self):
        self._inner = httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        ips = await resolve_public(host, port)
        return await self._inner.connect_tcp(ips[0], port, timeout=timeout, local_address=local_address, socket_options=socket_options)

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise BlockedAddress("Unix sockets are not allowed.")

    async def sleep(self, seconds):
        await self._inner.sleep(seconds)


def public_transport(**kw) -> httpx.AsyncHTTPTransport:
    transport = httpx.AsyncHTTPTransport(**kw)
    transport._pool._network_backend = _PublicOnlyBackend()
    return transport


def public_client(**kw) -> httpx.AsyncClient:
    """An AsyncClient that can only reach public internet addresses."""
    limits = kw.pop("limits", httpx.Limits(max_connections=100, max_keepalive_connections=20))
    return httpx.AsyncClient(transport=public_transport(limits=limits), **kw)


def private_model_urls_allowed() -> bool:
    flag = settings.allow_private_model_urls
    return (not settings.is_prod) if flag is None else flag


def model_client(**kw) -> httpx.AsyncClient:
    """Model-provider client: public addresses only, unless this install allows local/self-hosted model servers."""
    return httpx.AsyncClient(**kw) if private_model_urls_allowed() else public_client(**kw)


def check_url_shape(url: str, *, require_https: bool = False) -> str:
    u = urlparse(url.strip())
    if u.scheme not in (("https",) if require_https else ("http", "https")) or not u.hostname or u.username or u.password:
        raise ValueError("Use a plain " + ("https" if require_https else "http(s)") + " address without credentials.")
    return url.strip()
