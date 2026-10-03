"""Competitor monitoring (watched public feeds tested automatically), recurring trend re-runs, and the alerts both
produce. Called by the scheduler tick (dev loop or arq cron) and when an autopilot run completes."""
from __future__ import annotations

import ipaddress
import logging
import re
import socket
import xml.etree.ElementTree as ET
from datetime import timedelta
from html import unescape
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy import and_, or_, select

from app.core.errors import AppError
from app.db.base import utcnow
from app.db.session import session_scope
from app.models import Alert, Organization, Simulation, Watch
from app.services import lifecycle
from app.services.content.formats import FORMATS

log = logging.getLogger("kruvim.monitoring")
CHECK_EVERY = timedelta(minutes=60)
MAX_NEW_PER_CHECK = 3
MAX_BYTES = 2_000_000
WATCH_LIMITS = {"free": 0, "pro": 1, "business": 5, "enterprise": 50}
QUICK = {"voice": 40, "crowd": 1500, "stakeholders": 2, "hours": 12, "minutes_per_round": 60, "listening": False, "platforms": ["feed", "forum"]}


# ---- safe fetching ----------------------------------------------------------------------------------------------
def check_public_url(url: str) -> str:
    """Only public http(s) hosts: watched URLs come from users, so the server must not be steered at internal addresses."""
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise AppError("Use a public http(s) feed address.", code="bad_feed_url")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise AppError("That host name does not resolve.", code="bad_feed_url")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise AppError("Feeds on private or internal network addresses are not allowed.", code="bad_feed_url")
    return url.strip()


async def fetch(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"User-Agent": "KruvimMonitor/1.0"}) as client:
        for _ in range(4):
            check_public_url(url)
            async with client.stream("GET", url) as r:
                if r.is_redirect and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    continue
                r.raise_for_status()
                chunks, total = [], 0
                async for chunk in r.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise AppError("The feed is too large.")
                    chunks.append(chunk)
                return b"".join(chunks)
    raise AppError("Too many redirects.")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _text(el) -> str:
    raw = "".join(el.itertext()) if el is not None else ""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


def parse_feed(data: bytes) -> list[dict]:
    """RSS 2.0 and Atom (which covers YouTube channel feeds and most podcasts and newsletters)."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise AppError(f"That address is not a valid RSS or Atom feed ({exc}).", code="bad_feed")
    items = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        f = {_local(c.tag): c for c in node}
        link = f.get("link")
        href = (link.get("href") or link.text or "").strip() if link is not None else ""
        desc = next((f[k] for k in ("description", "summary", "content", "encoded") if k in f), None)
        if desc is None:      # YouTube keeps the description in media:group/media:description
            desc = next((d for d in node.iter() if _local(d.tag) == "description"), None)
        title = _text(f.get("title"))
        ident = _text(f.get("guid")) or _text(f.get("id")) or href or title
        if title or desc is not None:
            items.append({"id": ident[:300], "title": title[:300], "summary": _text(desc)[:4000], "link": href[:1000]})
    return items


# ---- watches ----------------------------------------------------------------------------------------------------
async def check_watch(watch_id: str) -> dict:
    async with session_scope() as s:
        w = await s.get(Watch, watch_id)
        if not w:
            return {"new": 0}
        url, seen = w.feed_url, list(w.seen or [])
    try:
        items = parse_feed(await fetch(url))
        err = None
    except Exception as exc:                                 # recorded on the watch, retried next tick
        items, err = [], str(exc)[:500]
    fresh = [i for i in items if i["id"] not in seen][:MAX_NEW_PER_CHECK]
    created = []
    async with session_scope() as s:
        w = await s.get(Watch, watch_id)
        w.last_checked_at, w.last_error = utcnow(), err
        if not seen and items:
            # first check: remember what is already there and test only the newest item
            w.seen = [i["id"] for i in items][-200:]
            fresh = items[:1]
        else:
            w.seen = (seen + [i["id"] for i in fresh])[-200:]
        fmt = FORMATS.get(w.format) or FORMATS["social_post"]
        for it in fresh:
            text = (it["title"] + "\n\n" + it["summary"]).strip()
            content = {"type": fmt["type"] if fmt["type"] == "text" else "text", "format": w.format if fmt["type"] == "text" else "social_post",
                       "platform": w.platform, "title": it["title"], "text": text, "goal": "", "seed_asset_ids": [], "asset_ids": [],
                       "poll_options": [], "source_url": it["link"], "b_kind": "version", "variant_b": None}
            sim = Simulation(org_id=w.org_id, project_id=w.project_id, created_by=w.created_by, name=f"{w.name} · {it['title'][:120] or 'new item'}",
                             requirement=f"How does the audience react to this new post from {w.name}, and does it outperform our own content?",
                             content=content, audience=w.audience or {}, config={"overrides": QUICK, "autopilot": True, "watch_id": w.id})
            s.add(sim)
            created.append(sim)
        await s.flush()
        ids = [x.id for x in created]
    for sid in ids:
        async with session_scope() as s:
            sim = await s.get(Simulation, sid)
            try:
                await lifecycle.queue_graph(s, sim)
            except Exception as exc:
                log.warning("could not start watch run %s: %s", sid, exc)
    return {"new": len(ids), "error": err, "simulations": ids}


async def due_watches() -> list[str]:
    cutoff = utcnow() - CHECK_EVERY
    async with session_scope() as s:
        rows = (await s.execute(select(Watch.id).where(and_(Watch.active.is_(True), or_(Watch.last_checked_at.is_(None), Watch.last_checked_at < cutoff)))
                                .limit(50))).all()
    return [r[0] for r in rows]


# ---- recurring re-runs -----------------------------------------------------------------------------------------
async def due_reruns() -> list[str]:
    async with session_scope() as s:
        rows = (await s.execute(select(Simulation).where(and_(Simulation.next_rerun_at.is_not(None), Simulation.next_rerun_at <= utcnow()))
                                .limit(50))).scalars().all()
        out = []
        for sim in rows:
            sim.next_rerun_at = utcnow() + timedelta(days=sim.rerun_every_days or 7)
            out.append(sim.id)
    for sid in out:
        async with session_scope() as s:
            sim = await s.get(Simulation, sid)
            try:
                new = await lifecycle.make_copy(s, sim, "rerun", autopilot=True)
                await lifecycle.queue_graph(s, new)
            except Exception as exc:
                log.warning("recurring re-run of %s failed to start: %s", sid, exc)
    return out


async def tick() -> dict:
    watches = await due_watches()
    for wid in watches:
        try:
            await check_watch(wid)
        except Exception:
            log.exception("watch check failed", extra={"job": "monitoring"})
    reruns = await due_reruns()
    return {"watches": len(watches), "reruns": len(reruns)}


# ---- after an autopilot run ------------------------------------------------------------------------------------
async def alert(org_id: str, kind: str, title: str, body: str = "", simulation_id: str | None = None, watch_id: str | None = None) -> None:
    async with session_scope() as s:
        s.add(Alert(org_id=org_id, kind=kind, title=title[:300], body=body, simulation_id=simulation_id, watch_id=watch_id))


async def on_completed(sim_id: str) -> None:
    async with session_scope() as s:
        sim = await s.get(Simulation, sim_id)
        cfg = sim.config or {}
        score = sim.score
        if score is None:
            return
        if cfg.get("watch_id"):
            w = await s.get(Watch, cfg["watch_id"])
            own = (await s.execute(select(Simulation.score, Simulation.config).where(and_(Simulation.org_id == sim.org_id, Simulation.score.is_not(None),
                                                                                         Simulation.id != sim.id)).limit(500))).all()
            mine = [sc for sc, c in own if not (c or {}).get("watch_id")]
            if not w:
                return
            if not mine:
                await alert(sim.org_id, "competitor_result", f"{w.name}: new post scored {score:.1f}/10",
                            "Run your own content through Kruvim to compare against it.", sim.id, w.id)
            else:
                base = sum(mine) / len(mine)
                if score >= base + w.threshold:
                    await alert(sim.org_id, "competitor_outscored", f"{w.name} outscored your average: {score:.1f} vs {base:.1f}",
                                f"Their new post \"{(sim.content or {}).get('title', '')[:120]}\" lands better with your audience than your own content does on average.",
                                sim.id, w.id)
        if cfg.get("rerun_of"):
            parent = await s.get(Simulation, cfg["rerun_of"])
            if parent and parent.score is not None and abs(score - parent.score) >= 0.3:
                way = "up" if score > parent.score else "down"
                await alert(sim.org_id, "rerun_changed", f"{parent.name}: opinion moved {way} to {score:.1f} (was {parent.score:.1f})",
                            "Same content and audience, re-run with today's news and trends.", sim.id)


async def on_failed(sim_id: str, message: str) -> None:
    async with session_scope() as s:
        sim = await s.get(Simulation, sim_id)
        if sim and (sim.config or {}).get("autopilot"):
            await alert(sim.org_id, "run_failed", f"Automatic run failed: {sim.name}", message[:1000], sim.id)


def watch_limit(org: Organization, is_superuser: bool) -> int:
    return 10_000 if is_superuser else WATCH_LIMITS.get(org.plan, 0)
