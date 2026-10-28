"""Messy and broken real-world files never crash an upload: each one is accepted or refused with a clear 4xx."""
from __future__ import annotations

import io
import zipfile

import pytest


def _docx(document_xml: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", document_xml)
    return buf.getvalue()


SEED_FILES = [
    ("corrupt.pdf", b"%PDF-1.4\n1 0 obj << /Type /Catalog >> broken xref", "application/pdf"),
    ("empty.txt", b"", "text/plain"),
    ("latin1.txt", "Enquête nationale: taux de chômage élevé à Marseille".encode("latin-1"), "text/plain"),
    ("binary.txt", bytes(range(256)) * 40, "text/plain"),
    ("not-a-zip.docx", b"this is not a word document", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("bomb.docx", _docx(b"<w:p><w:t>" + b"a" * (60 * 1024 * 1024) + b"</w:t></w:p>"),
     "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("mixed.md", "# Barometer\r\nQ1;Q2\r\n﻿42%;n/a\r\nالإمارات 17%".encode(), "text/markdown"),
]


@pytest.mark.parametrize(("name", "data", "mime"), SEED_FILES, ids=[f[0] for f in SEED_FILES])
async def test_seed_documents_never_crash(client, auth, name, data, mime):
    h, _ = auth
    pr = (await client.post("/projects", json={"name": "Messy"}, headers=h)).json()
    r = await client.post(f"/projects/{pr['id']}/assets", headers=h, data={"kind": "seed"}, files={"file": (name, data, mime)})
    assert r.status_code in (200, 413, 415, 422), r.text
    if r.status_code != 200:
        assert r.json()["error"]["message"]          # a readable reason, not a stack trace


DATASETS = [
    ("empty.csv", b""),
    ("header-only.csv", b"country,value\n"),
    ("ragged.csv", b"country,value\nAE,1,extra,cells\nSA\n"),
    ("dup-headers.csv", b"value,value\n1,2\n"),
    ("latin1.csv", "pays,valeur\nFrance,12,5\n".encode("latin-1")),
    ("semicolons.csv", b"country;value\nAE;1,5\nSA;n/a\n"),
    ("corrupt.xlsx", b"PK\x03\x04 truncated workbook"),
    ("binary.csv", bytes(range(256)) * 10),
]


@pytest.mark.parametrize(("name", "data"), DATASETS, ids=[d[0] for d in DATASETS])
async def test_dataset_uploads_never_crash(client, auth, name, data):
    h, _ = auth
    r = await client.post("/datapool/datasets", headers=h, data={"name": name}, files={"file": (name, data, "text/csv")})
    assert r.status_code in (200, 413, 422), r.text
    if r.status_code != 200:
        assert r.json()["error"]["message"]


@pytest.mark.parametrize(("name", "data"), [("corrupt.xlsx", b"PK\x03\x04 nope"), ("empty.csv", b""), ("junk.csv", bytes(range(256)))])
async def test_analytics_imports_never_crash(client, auth, name, data):
    h, _ = auth
    r = await client.post("/analytics/imports", headers=h, data={"platform": "tiktok", "kind": "posts", "aggregate_only": "true"},
                          files={"file": (name, data, "text/csv")})
    assert r.status_code in (200, 400, 413, 422), r.text


async def test_oversized_upload_is_refused_before_it_is_stored(client, auth, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    h, _ = auth
    pr = (await client.post("/projects", json={"name": "Big"}, headers=h)).json()
    r = await client.post(f"/projects/{pr['id']}/assets", headers=h, data={"kind": "seed"},
                          files={"file": ("big.txt", b"x" * (2 * 1024 * 1024), "text/plain")})
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_large"


async def test_unexpected_errors_return_json_with_a_reference(client):
    from app.db.session import get_session
    from app.main import app

    async def broken():
        raise RuntimeError("database exploded with secret detail")
        yield  # pragma: no cover

    app.dependency_overrides[get_session] = broken
    try:
        r = await client.get("/auth/me", headers={"Authorization": "Bearer x"})
    finally:
        app.dependency_overrides.clear()
    body = r.json()
    assert r.status_code == 500 and body["error"]["code"] == "internal_error"
    assert body["error"]["request_id"] == r.headers["x-request-id"] and "secret detail" not in r.text
