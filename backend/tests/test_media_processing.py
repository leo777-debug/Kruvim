import base64
import json
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from app.services.content import card, media
from app.services.llm.base import ProviderSettings, Usage
from app.services.llm.openai_compat import OpenAICompatLLM


@pytest.mark.parametrize('failure', ['exit', 'timeout', 'empty'])
def test_failed_extraction_never_reuses_stale_frames(monkeypatch, tmp_path, failure):
    stale = tmp_path / 'frame_00.jpg'
    stale.write_bytes(b'older frame from a previous attempt')
    monkeypatch.setattr(media, 'ffmpeg_tools', lambda: ('ffmpeg', 'ffprobe'))

    def run(*args, **kwargs):
        assert not stale.exists()
        if failure == 'timeout':
            raise subprocess.TimeoutExpired('ffmpeg', 60)
        if failure == 'empty':
            stale.write_bytes(b'')
            return SimpleNamespace(returncode=0)
        stale.write_bytes(b'partial invalid frame')
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(media.subprocess, 'run', run)
    assert media.extract_frames('video.mp4', [1], str(tmp_path)) == []


def test_transcription_adapter_and_empty_speech(monkeypatch):
    model = Mock()
    model.transcribe.return_value = ([SimpleNamespace(start=0, end=2, text=' Hello world. ')], None)
    factory = Mock(return_value=model)
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=factory))
    assert media.transcribe('speech.wav') == [{'start': 0, 'end': 2, 'text': 'Hello world.'}]
    model.transcribe.assert_called_once_with('speech.wav', vad_filter=True)
    model.transcribe.return_value = ([], None)
    with pytest.raises(media.ContentError, match='No speech'):
        media.transcribe('silent.wav')


def test_supplied_script_skips_transcription_and_missing_frames_are_disclosed(monkeypatch, tmp_path):
    monkeypatch.setattr(card, 'probe_duration', lambda path: 3)
    monkeypatch.setattr(card, 'has_video_stream', lambda path: False)
    transcribe = Mock(side_effect=AssertionError('Supplied script should bypass transcription'))
    monkeypatch.setattr(card, 'transcribe', transcribe)
    prep = card.prepare({'type': 'video', 'asset_id': 'a', 'text': 'A supplied video script.'}, {'a': 'video.mp4'}, str(tmp_path))
    assert prep['segments'][0]['text'] == 'A supplied video script.'
    assert any('visuals were not analysed' in note for note in prep['notes'])
    transcribe.assert_not_called()


def test_missing_transcriber_requests_transcript(monkeypatch):
    monkeypatch.setitem(sys.modules, 'faster_whisper', None)
    with pytest.raises(media.ContentError, match='needs a transcript'):
        media.transcribe('speech.wav')


def test_partial_frame_extraction_preserves_segment_alignment(monkeypatch, tmp_path):
    monkeypatch.setattr(card, 'probe_duration', lambda path: 12)
    monkeypatch.setattr(card, 'has_video_stream', lambda path: True)
    monkeypatch.setattr(card, 'extract_frames', lambda *args: [str(tmp_path / 'frame_01.jpg')])
    prep = card.prepare({'type': 'video', 'asset_id': 'a', 'transcript':
        '00:00:00.000 --> 00:00:06.000\nOpening\n\n00:00:06.000 --> 00:00:12.000\nEnding'},
        {'a': 'video.mp4'}, str(tmp_path))
    assert 'frame' not in prep['segments'][0]
    assert prep['segments'][1]['frame'].endswith('frame_01.jpg')
    assert any('incomplete' in note for note in prep['notes'])


async def test_real_ffmpeg_frames_reach_vision_model(tmp_path):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg/ffprobe required for integration check')
    video = str(tmp_path / 'blue.mp4')
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=128x128:d=2',
                    '-c:v', 'mpeg4', video], check=True, capture_output=True, timeout=30)
    prep = card.prepare({'type': 'video', 'asset_id': 'a', 'transcript': 'The blue product is ready.'},
                        {'a': video}, str(tmp_path / 'work'))
    assert 1.9 <= prep['duration'] <= 2.1
    assert prep['segments'][0]['frame']
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body['model'] == 'vision-test'
        images = [part['image_url']['url'] for part in body['messages'][1]['content'] if part['type'] == 'image_url']
        assert images and base64.b64decode(images[0].split(',')[1]).startswith(b'\xff\xd8')
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({
            'summary': 'A blue product with a spoken introduction.', 'segment_labels': ['Opening'],
            'segment_notes': ['Blue image supplied.']})}}], 'usage': {'prompt_tokens': 20, 'completion_tokens': 15}})

    llm = OpenAICompatLLM(ProviderSettings(base_url='https://model.example/v1', report_model='text-test', vision_model='vision-test'))
    await llm.client.aclose()
    llm.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        result = await card.build_card(prep, {'platform': 'tiktok'}, llm, Usage())
    finally:
        await llm.aclose()
    assert len(requests) == 1
    assert result['visual_analysis'] == {'status': 'analysed', 'images': 1}
    assert result['analysed_by'] == 'vision-test'


async def test_no_vision_model_reports_unanalysed_image(tmp_path):
    image = tmp_path / 'image.jpg'
    image.write_bytes(b'example image bytes')
    prep = card.prepare({'type': 'image', 'asset_id': 'a'}, {'a': str(image)}, str(tmp_path))
    llm = OpenAICompatLLM(ProviderSettings(base_url='https://model.example/v1', report_model='text-test'))
    await llm.client.aclose()

    def respond(request):
        assert isinstance(json.loads(request.content)['messages'][1]['content'], str)
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"summary":"Text only"}'}}]})

    llm.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        result = await card.build_card(prep, {}, llm, Usage())
    finally:
        await llm.aclose()
    assert result['visual_analysis']['status'] == 'not_analysed'
    assert 'No vision model configured: visuals were not analysed.' in result['notes']
