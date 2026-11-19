import base64
import io
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from pydantic import ValidationError

from app.schemas.simulation import ContentIn, LocalImage, LocalMedia
from app.services.content.card import build_card, prepare
from app.services.llm.base import Usage


def jpeg(color="red", size=(64, 48)):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


def test_derived_images_are_bounded_and_timed():
    with pytest.raises(ValidationError):
        LocalImage(data="data:video/mp4;base64,AAAA", order=0)
    with pytest.raises(ValidationError):
        LocalImage(data=jpeg(size=(1025, 2)), order=0)
    with pytest.raises(ValidationError):
        LocalMedia(duration=3, images=[LocalImage(data=jpeg(), time=4, order=0)])
    with pytest.raises(ValidationError):
        LocalMedia(images=[LocalImage(data=jpeg(), order=0), LocalImage(data=jpeg(), order=0)])


def test_browser_media_preserves_duration_cues_carousel_and_b(tmp_path):
    content = ContentIn(
        type="video",
        transcript="00:00:02,000 --> 00:00:05,000\nOpening.\n\n00:00:07,000 --> 00:00:10,000\nEnding.",
        local_media={"duration": 12, "images": [{"data": jpeg(), "time": 8, "order": 0}]},
        variant_b={
            "type": "image",
            "description": "Red slide\nBlue slide",
            "local_media": {"images": [{"data": jpeg(), "order": 0}, {"data": jpeg("blue"), "order": 1}]},
        },
    ).model_dump()
    a = prepare(content, {}, str(tmp_path))
    assert a["duration"] == 12 and a["segments"][0]["start"] == 2
    assert a["segments"][-1]["end"] == 10 and len(a["images"]) == 1
    assert any("8.00s" in note for note in a["notes"])
    b = prepare(content["variant_b"], {}, str(tmp_path))
    assert [s["text"] for s in b["segments"]] == ["Red slide", "Blue slide"]
    assert [im[1] for im in b["images"]] == [jpeg().split(",")[1], jpeg("blue").split(",")[1]]


@pytest.mark.asyncio
async def test_cloud_vision_receives_only_selected_jpegs_and_timing(tmp_path):
    from unittest.mock import Mock

    llm = Mock(is_dry=False)
    llm.has_vision.return_value = True
    llm.model_for.return_value = "backend-vision-model"
    llm.complete_json = AsyncMock(return_value={"summary": "A breakfast recipe"})
    prep = prepare(
        {
            "type": "video",
            "transcript": "00:00:00,000 --> 00:00:04,000\nBreakfast recipe.",
            "local_media": {"duration": 4, "images": [{"data": jpeg(), "time": 2, "order": 0}]},
        },
        {},
        str(tmp_path),
    )
    result = await build_card(prep, {"format": "short_video"}, llm, Usage())
    sent = llm.complete_json.call_args.kwargs
    assert sent["images"] == [("image/jpeg", jpeg().split(",")[1])]
    assert "[2]" in sent["user"]
    assert result["duration"] == 4 and result["visual_analysis"]["status"] == "analysed"


@pytest.mark.asyncio
async def test_extracted_background_never_uses_object_storage(client, auth, monkeypatch):
    from app.db.session import session_scope
    from app.models import Asset
    from app.services import storage

    h, _ = auth
    put, get, delete = AsyncMock(side_effect=AssertionError("Original storage must not be used")), AsyncMock(), AsyncMock()
    monkeypatch.setattr(storage, "put", put)
    monkeypatch.setattr(storage, "get", get)
    monkeypatch.setattr(storage, "delete", delete)
    pr = (await client.post("/projects", json={"name": "Local context"}, headers=h)).json()
    response = await client.post(
        f"/projects/{pr['id']}/assets/extracted-text",
        headers=h,
        json={"filename": "brief.pdf", "text": "Preserved document context."},
    )
    assert response.status_code == 200, response.text
    asset = response.json()
    async with session_scope() as s:
        row = await s.get(Asset, asset["id"])
        assert row.storage_key == "" and row.text_excerpt == "Preserved document context."
    assert (await client.delete(f"/assets/{asset['id']}", headers=h)).status_code == 200
    put.assert_not_called()
    get.assert_not_called()
    delete.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,report_status", [("completed", "queued"), ("completed", "running"), ("building_graph", "none"), ("preparing", "none")]
)
async def test_project_deletion_preserves_active_pipeline_work(client, auth, status, report_status):
    from app.db.session import session_scope
    from app.models import Simulation

    headers, _ = auth
    project = (await client.post("/projects", headers=headers, json={"name": "Active report protection"})).json()
    response = await client.post(
        f"/projects/{project['id']}/simulations",
        headers=headers,
        json={"content": {"type": "text", "text": "A synthetic test post."}},
    )
    assert response.status_code == 200, response.text
    sim_id = response.json()["id"]
    async with session_scope() as session:
        sim = await session.get(Simulation, sim_id)
        sim.status = status
        sim.report_status = report_status
        await session.commit()
    response = await client.delete(f"/projects/{project['id']}", headers=headers)
    assert response.status_code == 409 and "reports" in response.json()["error"]["message"]
    assert (await client.get(f"/simulations/{sim_id}", headers=headers)).status_code == 200
    async with session_scope() as session:
        sim = await session.get(Simulation, sim_id)
        sim.status = "completed"
        sim.report_status = "done"
        await session.commit()
    assert (await client.delete(f"/projects/{project['id']}", headers=headers)).status_code == 200
