"""Free GDELT event records, expressed as coded reports with original news links."""
import csv
import io
import re
import zipfile
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from ..base import BaseConnector, ConnectorSpec, SignalItem
from .publisher_rss import geographies

BASE_URL = "https://data.gdeltproject.org/gdeltv2/"
FIPS_COUNTRIES = {"GB": "UK", "MA": "MO"}
ROOTS = {
    "01": "public statement", "02": "appeal", "03": "intent to cooperate", "04": "consultation",
    "05": "diplomatic cooperation", "06": "material cooperation", "07": "aid", "08": "yielding",
    "09": "investigation", "10": "demand", "11": "disapproval", "12": "rejection", "13": "threat",
    "14": "protest", "15": "military posture", "16": "reduced relations", "17": "coercion",
    "18": "assault", "19": "fighting", "20": "unconventional mass violence",
}


def parse_events(raw, regions, now):
    if len(raw) > 5 * 1024 * 1024:
        raise ValueError("GDELT event download exceeds 5 MB")
    out = []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        files = archive.infolist()
        if len(files) != 1 or files[0].file_size > 25 * 1024 * 1024:
            raise ValueError("GDELT event archive exceeds expected bounds")
        with archive.open(files[0]) as stream:
            for index, row in enumerate(csv.reader(io.TextIOWrapper(stream, encoding="utf-8"), delimiter="\t")):
                if index >= 20000:
                    raise ValueError("GDELT event archive exceeds 20,000 records")
                if len(row) != 61 or not row[0].isdecimal() or row[28] not in ROOTS:
                    continue
                try:
                    added = datetime.strptime(row[59], "%Y%m%d%H%M%S").replace(tzinfo=UTC)
                    event_day = datetime.strptime(row[1], "%Y%m%d").date()
                    url = urlparse(row[60])
                except ValueError:
                    continue
                if (not now - timedelta(hours=2) <= added <= now or not
                        now.date() - timedelta(days=1) <= event_day <= now.date()
                        or url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password):
                    continue
                local = geographies(row[52]) if row[53] == "AE" else []
                for region in regions:
                    country = region.get("country") or region["code"].split("-")[0]
                    if row[53] != FIPS_COUNTRIES.get(country, country):
                        continue
                    if local and local != ["AE"] and region["code"] not in local:
                        continue
                    title = (f"GDELT coded report — {row[6] or 'unspecified actor'} / "
                             f"{ROOTS[row[28]]} / {row[16] or 'unspecified counterpart'} — {row[52]} ({event_day})")
                    out.append(SignalItem("headline", region["code"], title, url=row[60], observed_at=added,
                        payload={"event_id": row[0], "event_date": str(event_day), "event_code": row[26],
                            "event_category": ROOTS[row[28]], "action_location": row[52],
                            "actor1": row[6], "actor2": row[16], "collector": "gdelt_events",
                            "timestamp_kind": "GDELT ingestion time", "country_code": row[53],
                            "geography_match": "location" if local and local != ["AE"] else "country",
                            "dataset_url": "https://www.gdeltproject.org/",
                            "summary": "Automated GDELT event coding from a news report. Classification may be inaccurate. "
                                       "The source link identifies the original report."}))
    return out


class GdeltEventsConnector(BaseConnector):
    spec = ConnectorSpec("gdelt_events", "GDELT free news events", "news",
        "Recent news events from GDELT's public 15-minute files, with source links and coded event dates.",
        interval_minutes=10, license_note="Free GDELT Project datasets. Attribution retained; source article text is not fetched.",
        docs_url="https://www.gdeltproject.org/about.html")

    async def fetch(self, client, regions, secrets, config):
        response = await client.get(BASE_URL + "lastupdate.txt")
        response.raise_for_status()
        match = re.search(r"\b(\d{14})\.export\.CSV\.zip\b", response.text[:4096])
        if not match:
            raise ValueError("GDELT index has no event export")
        latest = datetime.strptime(match[1], "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        now = datetime.now(UTC)
        # An index may announce the next quarter-hour batch before its timestamp.
        # Read the previous completed batch and retain every record's native time.
        if now < latest <= now + timedelta(minutes=15):
            latest -= timedelta(minutes=15)
        if not now - timedelta(hours=2) <= latest <= now:
            raise ValueError("GDELT latest event export is stale or future-dated")
        out, seen, counts = [], set(), {}
        # Read the last hour to recover between ten-minute scheduler invocations.
        for offset in range(4):
            stamp = (latest - timedelta(minutes=15 * offset)).strftime("%Y%m%d%H%M%S")
            response = await client.get(BASE_URL + stamp + ".export.CSV.zip")
            if offset and response.status_code == 404:
                continue
            response.raise_for_status()
            for item in parse_events(response.content, regions, now):
                identity = (item.region, item.payload["event_id"])
                if identity not in seen and counts.get(item.region, 0) < 10:
                    out.append(item)
                    seen.add(identity)
                    counts[item.region] = counts.get(item.region, 0) + 1
        return out
