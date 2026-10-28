"""Barometer library: messy files kept verbatim with provenance, duplicates and bad files handled, isolation, retrieval."""
from __future__ import annotations

import io

MESSY_CSV = ("Enquête Barometre Q3 ;;  \n"
             "Source: Office national (provisoire)\n"
             "Région;Chômage %;  Confiance\n"
             "Île-de-France ; 7,1 ;n/d\n"
             "  Occitanie;9.4;  42\n"
             "* chiffres révisés, voir note 3\n").encode()


def _form(**kw):
    base = {"country": "FR", "publisher": "INSEE", "title": "Baromètre régional", "published_on": "2026-09-30",
            "source_url": "https://example.org/barometre"}
    return {**base, **kw}


async def _upload(client, h, name="barometre.csv", data=MESSY_CSV, **kw):
    return await client.post("/barometers", headers=h, data=_form(**kw), files={"file": (name, data, "application/octet-stream")})


async def test_messy_file_is_kept_verbatim_with_provenance(client, auth):
    h, _ = auth
    r = await _upload(client, h)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["status"] == "ready" and doc["chunk_count"] >= 1 and doc["encoding"] == "utf-8"
    assert (doc["country"], doc["publisher"], doc["published_on"], doc["filename"]) == ("FR", "INSEE", "2026-09-30", "barometre.csv")
    assert len(doc["sha256"]) == 64

    original = await client.get(f"/barometers/{doc['id']}/file", headers=h)
    assert original.content == MESSY_CSV and original.headers["content-disposition"].startswith("attachment")
    detail = (await client.get(f"/barometers/{doc['id']}", headers=h)).json()
    text = "".join(c["text"] for c in detail["preview"])
    # Nothing tidied: odd spacing, decimal commas, n/d and footnotes are all still there.
    assert "Île-de-France ; 7,1 ;n/d" in text and "  Occitanie;9.4;  42" in text and "* chiffres révisés" in text


async def test_duplicates_are_refused_with_a_pointer(client, auth):
    h, _ = auth
    first = (await _upload(client, h)).json()
    again = await _upload(client, h, name="copy.csv", title="Same file, new name")
    assert again.status_code == 409 and again.json()["error"]["details"]["document_id"] == first["id"]


async def test_encodings_and_workbooks(client, auth):
    from openpyxl import Workbook
    h, _ = auth
    r = await _upload(client, h, name="latin.csv", data="Région;Taux\nCôte d'Azur;12,5\n".encode("cp1252"))
    assert r.json()["status"] == "ready" and r.json()["encoding"] == "cp1252"
    assert "Côte d'Azur;12,5" in (await client.get(f"/barometers/{r.json()['id']}", headers=h)).json()["preview"][0]["text"]

    wb = Workbook()
    ws = wb.active
    ws.title = "T3 2026"
    ws.append(["Tableau 4 - Confiance (en %)", None, None])
    ws.append([None, None, None])
    ws.append(["Âge", "Oui", "Non / NSP"])
    ws.append(["18-24", 41.5, "58,5*"])
    buf = io.BytesIO()
    wb.save(buf)
    r = await _upload(client, h, name="tableau.xlsx", data=buf.getvalue())
    detail = (await client.get(f"/barometers/{r.json()['id']}", headers=h)).json()
    assert detail["status"] == "ready" and detail["preview"][0]["location"].startswith("sheet T3 2026")
    assert "18-24\t41.5\t58,5*" in detail["preview"][0]["text"]


async def test_bad_files_are_quarantined_or_refused(client, auth):
    from pypdf import PdfWriter
    h, _ = auth
    blank = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(blank)
    cases = {"corrupt.pdf": b"%PDF-1.4 broken", "scanned.pdf": blank.getvalue(), "empty.csv": b"",
             "binary.csv": bytes(range(256)) * 20, "fake.xlsx": b"PK\x03\x04 nope", "fake.docx": b"not a document"}
    for name, data in cases.items():
        r = await _upload(client, h, name=name, data=data)
        assert r.status_code == 200, (name, r.text)
        assert r.json()["status"] == "quarantined" and r.json()["quarantine_reason"], name
    assert "scanned" in (await _upload(client, h, name="s2.pdf", data=blank.getvalue() + b"\n%x")).json()["quarantine_reason"]

    r = await _upload(client, h, name="tool.exe", data=b"MZ\x90\x00")
    assert r.status_code == 415
    quarantined = (await client.get("/barometers?status=quarantined", headers=h)).json()["documents"]
    assert len(quarantined) == 7
    # Quarantined files never reach search results.
    assert (await client.get("/barometers/search?q=scanned", headers=h)).json()["results"] == []


async def test_provenance_is_validated(client, auth):
    h, _ = auth
    assert (await _upload(client, h, country="France")).json()["error"]["code"] == "bad_country"
    assert (await _upload(client, h, publisher="  ")).json()["error"]["code"] == "publisher_required"
    assert (await _upload(client, h, source_url="javascript:alert(1)")).json()["error"]["code"] == "bad_source_url"
    assert (await _upload(client, h, published_on="2999-01-01")).json()["error"]["code"] == "bad_published_on"
    assert (await _upload(client, h, published_on="last spring")).json()["error"]["code"] == "bad_published_on"


async def test_workspace_documents_are_private_and_shared_ones_are_not(client, auth):
    ha, _ = auth                                       # first account: platform admin in the test environment
    private = (await _upload(client, ha)).json()
    shared = (await _upload(client, ha, name="shared.csv", data=b"country,trust\nFR,41\n", shared="true")).json()
    assert shared["scope"] == "shared"

    r = await client.post("/auth/register", json={"email": "b@example.com", "password": "another-password-1", "org_name": "B"})
    hb = {"Authorization": f"Bearer {r.json()['access_token']}"}
    listed = {d["id"] for d in (await client.get("/barometers", headers=hb)).json()["documents"]}
    assert listed == {shared["id"]}
    for path in (f"/barometers/{private['id']}", f"/barometers/{private['id']}/file"):
        assert (await client.get(path, headers=hb)).status_code == 404
    assert (await client.delete(f"/barometers/{private['id']}", headers=hb)).status_code == 404
    assert (await client.delete(f"/barometers/{shared['id']}", headers=hb)).status_code == 403
    assert (await _upload(client, hb, name="x.csv", data=b"a,b\n1,2\n", shared="true")).status_code == 403
    hits = (await client.get("/barometers/search?q=chômage Occitanie", headers=hb)).json()["results"]
    assert all(x["document_id"] != private["id"] for x in hits)


async def test_search_ranks_relevant_text_and_filters_by_country(client, auth):
    h, _ = auth
    await _upload(client, h)
    await _upload(client, h, name="ae.txt", country="AE", publisher="FCSC", title="Household survey",
                  data=b"Average household size in Dubai 4.2 persons; Abu Dhabi 5.1 (provisional)")
    hits = (await client.get("/barometers/search?q=household size Dubai", headers=h)).json()["results"]
    assert hits[0]["publisher"] == "FCSC" and hits[0]["location"] and "4.2 persons" in hits[0]["text"]
    only_fr = (await client.get("/barometers/search?q=household size Dubai&country=FR", headers=h)).json()["results"]
    assert {x["country"] for x in only_fr} == {"FR"}


async def test_simulations_receive_relevant_excerpts_with_sources(client, auth):
    from app.services.barometers import world_lines
    from tests.test_e2e_dry import SCRIPT, wait_for
    h, _ = auth
    await _upload(client, h, name="gym.txt", country="AE", publisher="Dubai Sports Council", title="Fitness participation 2026",
                  data=b"Share of adults exercising weekly: 38% (2025: 35%). Gym memberships cancelled within 3 months: about half.")
    pr = (await client.post("/projects", json={"name": "Fitness"}, headers=h)).json()
    body = {"name": "Gym video", "requirement": "Will Dubai adults exercising at home share this fitness routine?",
            "content": {"type": "video", "title": "Apartment workout", "platform": "tiktok", "transcript": SCRIPT},
            "audience": {"regions": ["AE"]},
            "overrides": {"voice": 10, "crowd": 500, "stakeholders": 1, "hours": 2, "minutes_per_round": 60, "listening": False}}
    sid = (await client.post(f"/projects/{pr['id']}/simulations", json=body, headers=h)).json()["id"]
    await client.post(f"/simulations/{sid}/graph", headers=h)
    await wait_for(client, h, sid, "status", {"graph_ready"})
    await client.post(f"/simulations/{sid}/environment", headers=h)
    sim = await wait_for(client, h, sid, "status", {"ready"})
    used = sim["config"]["barometers"]
    assert used and used[0]["publisher"] == "Dubai Sports Council" and "38%" in used[0]["text"]
    block = world_lines(used)
    assert "[Dubai Sports Council, AE" in block and "unedited" in block


async def test_deleting_removes_the_document_and_its_index(client, auth):
    from sqlalchemy import func, select

    from app.db.session import session_scope
    from app.models import BarometerChunk
    h, _ = auth
    doc = (await _upload(client, h)).json()
    assert (await client.delete(f"/barometers/{doc['id']}", headers=h)).status_code == 200
    assert (await client.get(f"/barometers/{doc['id']}", headers=h)).status_code == 404
    async with session_scope() as s:
        assert (await s.execute(select(func.count()).select_from(BarometerChunk))).scalar() == 0
    # The same file can be added again afterwards.
    assert (await _upload(client, h)).status_code == 200
