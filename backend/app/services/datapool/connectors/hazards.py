"""Primary natural-event feeds also used by World Monitor. No dashboard scraping."""
from datetime import UTC, datetime, timedelta
from math import asin, cos, isfinite, radians, sin, sqrt

from ..base import BaseConnector, ConnectorSpec, SignalItem

USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson"
EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"


def timestamp(value):
    try:
        result = (datetime.fromtimestamp(value / 1000, UTC) if isinstance(value, (int, float))
                  else datetime.fromisoformat(str(value).replace("Z", "+00:00")))
        return result.astimezone(UTC) if result.tzinfo else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def nearby(regions, coordinates, radius):
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return []
    try:
        lon, lat = map(float, coordinates[:2])
        if not isfinite(lat) or not isfinite(lon) or abs(lat) > 90 or abs(lon) > 180:
            return []
    except (TypeError, ValueError):
        return []
    matches = []
    for region in regions:
        a, b = radians(lat), radians(region["lat"])
        h = sin((a - b) / 2) ** 2 + cos(a) * cos(b) * sin(radians(lon - region["lon"]) / 2) ** 2
        distance = 12742 * asin(min(1, sqrt(max(0, h))))
        if distance <= radius:
            matches.append((region, round(distance, 1)))
    return matches


def radius_of(config):
    value = float(config.get("radius_km", 500))
    if not isfinite(value) or not 10 <= value <= 1500:
        raise ValueError("Hazard radius_km must be between 10 and 1500")
    return value


def items_for(regions, coordinates, radius, *, event_id, title, category, observed, now, url, extra=None):
    return [SignalItem("natural_hazard", reg["code"],
        f"{title[:350]} ({distance:g} km from {reg['city']}; proximity does not establish local impact)",
        url=url, observed_at=observed, payload={
            "event_id": str(event_id)[:160], "category": category,
            "event_at": observed.isoformat(), "checked_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=2)).isoformat(),
            "distance_km": distance, "coordinates": coordinates[:2],
            "summary": "Reported natural event near the regional reference point. Local damage, personal exposure and awareness are unknown.",
            **(extra or {})}) for reg, distance in nearby(regions, coordinates, radius)]


class UsgsConnector(BaseConnector):
    spec = ConnectorSpec("usgs_earthquakes", "USGS earthquakes", "events",
        "M4.5+ earthquakes in the last seven days, matched by distance to audience regions.",
        interval_minutes=30, docs_url="https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php",
        license_note="USGS feed. Preserve attribution; source approval is managed in Sources.")

    async def fetch(self, client, regions, secrets, config):
        radius, now = radius_of(config), datetime.now(UTC)
        response = await client.get(USGS_URL)
        response.raise_for_status()
        out = []
        for event in response.json().get("features", [])[:1000]:
            try:
                p, geometry = event["properties"], event["geometry"]
                observed = timestamp(p.get("time"))
                magnitude = float(p["mag"])
                if (not observed or not now - timedelta(days=7) <= observed <= now or
                        not isfinite(magnitude) or magnitude < 4.5 or geometry.get("type") != "Point" or not event.get("id")):
                    continue
                out.extend(items_for(regions, geometry["coordinates"], radius,
                    event_id=event["id"], title=f"USGS M{magnitude:g} earthquake: {p.get('place') or 'location unspecified'}",
                    category="earthquake", observed=observed, now=now,
                    url=f"https://earthquake.usgs.gov/earthquakes/eventpage/{event['id']}",
                    extra={"magnitude": magnitude, "alert": p.get("alert"), "updated_at": p.get("updated")}))
            except (KeyError, TypeError, ValueError):
                continue
        return out


class EonetConnector(BaseConnector):
    spec = ConnectorSpec("nasa_eonet", "NASA EONET natural events", "events",
        "Open storms, wildfires, floods and other natural events with dated point locations.",
        interval_minutes=30, docs_url="https://eonet.gsfc.nasa.gov/docs/v3",
        license_note="EONET curated metadata. Retain underlying source attribution; review reuse in Sources.")

    async def fetch(self, client, regions, secrets, config):
        radius, now = radius_of(config), datetime.now(UTC)
        response = await client.get(EONET_URL, params={"status": "open", "days": 30, "limit": 500})
        response.raise_for_status()
        out = []
        for event in response.json().get("events", [])[:500]:
            try:
                if event.get("closed") or not event.get("id"):
                    continue
                points = [(timestamp(g.get("date")), g) for g in event.get("geometry", []) if g.get("type") == "Point"]
                points = [(date, g) for date, g in points if date and now - timedelta(days=30) <= date <= now]
                if not points:
                    continue
                observed, geometry = max(points, key=lambda pair: pair[0])
                categories = [str(c["id"]) for c in event.get("categories", []) if c.get("id")]
                if "earthquakes" in categories:
                    continue  # USGS is the earthquake authority for this integration.
                out.extend(items_for(regions, geometry["coordinates"], radius,
                    event_id=event["id"], title=f"NASA EONET: {event['title']}",
                    category=", ".join(categories) or "natural_event", observed=observed, now=now,
                    url=f"https://eonet.gsfc.nasa.gov/api/v3/events/{event['id']}",
                    extra={"sources": event.get("sources", []), "magnitude": geometry.get("magnitudeValue"),
                           "magnitude_unit": geometry.get("magnitudeUnit"), "status": "open"}))
            except (KeyError, TypeError, ValueError):
                continue
        return out


def current_hazards(items, at):
    """Select the newest checked revision; expired revisions cannot reappear as active."""
    seen, out = set(), []
    for item in items:  # caller orders newest retrieval first
        if item.kind != "natural_hazard":
            out.append(item)
            continue
        key = (item.source, item.region, item.payload.get("event_id", item.id))
        if key in seen:
            continue
        seen.add(key)
        expires = timestamp(item.payload.get("expires_at"))
        if expires and expires > at:
            out.append(item)
    return out
