"""Keyless environmental and calendar sources: weather, public holidays + lunar calendar, FX."""
from __future__ import annotations

import asyncio
import datetime as dt

from ..base import BaseConnector, ConnectorSpec, SignalItem

WEATHER_CODES = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog", 51: "light drizzle",
                 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 71: "light snow", 73: "snow",
                 75: "heavy snow", 80: "showers", 81: "showers", 82: "violent showers", 95: "thunderstorm", 96: "thunderstorm with hail",
                 99: "thunderstorm with hail"}

# Astronomical estimates; actual observance may shift by a day.
ISLAMIC = [("2026-02-18", "Ramadan begins (est.)"), ("2026-03-20", "Eid al-Fitr (est.)"), ("2026-05-27", "Eid al-Adha (est.)"),
           ("2026-06-16", "Islamic New Year (est.)"), ("2026-08-25", "Mawlid (est.)"), ("2027-02-08", "Ramadan begins (est.)"),
           ("2027-03-10", "Eid al-Fitr (est.)"), ("2027-05-16", "Eid al-Adha (est.)"), ("2027-06-06", "Islamic New Year (est.)"),
           ("2027-08-15", "Mawlid (est.)"), ("2028-01-28", "Ramadan begins (est.)"), ("2028-02-27", "Eid al-Fitr (est.)")]
NATIONAL = {"AE": [("11-30", "Commemoration Day"), ("12-02", "UAE National Day")], "SA": [("02-22", "Founding Day"), ("09-23", "Saudi National Day")],
            "JO": [("05-25", "Independence Day")], "IN": [("01-26", "Republic Day"), ("08-15", "Independence Day"), ("10-02", "Gandhi Jayanti")]}
ISLAMIC_REGIONS = {"AE", "SA", "EG", "JO", "MA"}


class WeatherConnector(BaseConnector):
    spec = ConnectorSpec("open_meteo", "Open-Meteo weather", "weather", "Current temperature, feels-like, conditions per city.",
                         interval_minutes=60, license_note="Free tier is non-commercial; buy an API plan for SaaS use.",
                         docs_url="https://open-meteo.com/")

    async def fetch(self, client, regions, secrets, config):
        async def one(reg):
            r = await client.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": reg["lat"], "longitude": reg["lon"], "timezone": "auto",
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day"})
            r.raise_for_status()
            c = r.json()["current"]
            text = WEATHER_CODES.get(c.get("weather_code"), "unknown")
            return SignalItem("weather", reg["code"], f"{reg['city']}: {c.get('temperature_2m'):.0f}°C, {text}",
                              value=c.get("apparent_temperature"),
                              payload={"temp_c": c.get("temperature_2m"), "feels_c": c.get("apparent_temperature"),
                                       "humidity": c.get("relative_humidity_2m"), "wind_kmh": c.get("wind_speed_10m"),
                                       "text": text, "local_time": c.get("time"), "is_day": bool(c.get("is_day"))})
        res = await asyncio.gather(*[one(r) for r in regions], return_exceptions=True)
        return [x for x in res if isinstance(x, SignalItem)]


class CalendarConnector(BaseConnector):
    spec = ConnectorSpec("calendar", "Holidays & religious calendar", "events",
                         "Public holidays (Nager.Date) plus Islamic and national days for regions Nager does not cover.",
                         interval_minutes=720, docs_url="https://date.nager.at/")

    async def fetch(self, client, regions, secrets, config):
        out: list[SignalItem] = []
        today = dt.date.today()
        horizon = today + dt.timedelta(days=60)
        for reg in regions:
            events = []
            try:
                r = await client.get(f"https://date.nager.at/api/v3/NextPublicHolidays/{reg['holiday_cc']}")
                if r.status_code == 200 and r.content:
                    for h in r.json():
                        d = dt.date.fromisoformat(h["date"])
                        if d <= horizon:
                            events.append((h["date"], h["name"], "Nager.Date"))
            except Exception:
                pass
            if reg["code"] in ISLAMIC_REGIONS:
                for ds, name in ISLAMIC:
                    d = dt.date.fromisoformat(ds)
                    if today <= d <= horizon and not any(name.split(" (")[0] in e[1] for e in events):
                        events.append((ds, name, "lunar estimate"))
            for md, name in NATIONAL.get(reg["code"], []):
                for y in (today.year, today.year + 1):
                    d = dt.date.fromisoformat(f"{y}-{md}")
                    if today <= d <= horizon and not any(e[0] == d.isoformat() for e in events):
                        events.append((d.isoformat(), name, "built-in"))
            for ds, name, src in sorted(events)[:6]:
                days = (dt.date.fromisoformat(ds) - today).days
                out.append(SignalItem("event", reg["code"], name, value=float(days),
                                      payload={"date": ds, "days_away": days, "source": src}))
        return out


class FxConnector(BaseConnector):
    spec = ConnectorSpec("fx_rates", "Exchange rates", "economy", "Daily USD exchange rates for regional currencies.",
                         interval_minutes=720, docs_url="https://www.exchangerate-api.com/docs/free")
    CUR = {"AE": "AED", "SA": "SAR", "EG": "EGP", "JO": "JOD", "MA": "MAD", "GB": "GBP", "IN": "INR"}

    async def fetch(self, client, regions, secrets, config):
        r = await client.get("https://open.er-api.com/v6/latest/USD")
        r.raise_for_status()
        rates = r.json().get("rates", {})
        out = []
        for reg in regions:
            cur = self.CUR.get(reg["code"])
            if cur and cur in rates:
                out.append(SignalItem("economy", reg["code"], f"USD/{cur} {rates[cur]:.3f}", value=float(rates[cur]),
                                      payload={"currency": cur}))
        return out
