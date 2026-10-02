"""Media helpers: subtitles, transcription (optional faster-whisper), ffmpeg frames, document text."""
from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import subprocess

_TS = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")


class ContentError(Exception):
    pass


def _secs(m) -> float:
    return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4).ljust(3, "0")) / 1000


def parse_subtitles(text: str) -> list[dict]:
    cues = []
    for b in re.split(r"\n\s*\n", text.replace("\r", "")):
        lines = [x for x in b.split("\n") if x.strip()]
        for k, line in enumerate(lines):
            if "-->" in line:
                a, _, z = line.partition("-->")
                ma, mz = _TS.search(a), _TS.search(z)
                if ma and mz:
                    body = " ".join(re.sub(r"<[^>]+>", "", x) for x in lines[k + 1:]).strip()
                    if body:
                        cues.append({"start": _secs(ma), "end": _secs(mz), "text": body})
                break
    return cues


def looks_like_subtitles(text: str) -> bool:
    return "-->" in text and bool(_TS.search(text))


def ffmpeg_tools():
    return shutil.which("ffmpeg"), shutil.which("ffprobe")


def probe_duration(path: str) -> float | None:
    _, probe = ffmpeg_tools()
    if not probe:
        return None
    try:
        out = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
                             capture_output=True, text=True, timeout=30)
        return float(json.loads(out.stdout)["format"]["duration"])
    except Exception:
        return None


def has_video_stream(path: str) -> bool:
    _, probe = ffmpeg_tools()
    if not probe:
        return False
    try:
        out = subprocess.run([probe, "-v", "error", "-select_streams", "v", "-show_entries", "stream=codec_type", "-of", "json", path],
                             capture_output=True, text=True, timeout=30)
        return bool(json.loads(out.stdout).get("streams"))
    except Exception:
        return False


def transcribe(path: str) -> list[dict]:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        raise ContentError("This file needs a transcript. Paste one (plain text, SRT or VTT) or enable local transcription "
                           "(install faster-whisper on the worker).")
    model = WhisperModel(os.environ.get("KRUVIM_WHISPER_MODEL", "small"), device="auto", compute_type="int8")
    segments, _ = model.transcribe(path, vad_filter=True)
    return [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments if s.text.strip()]


def extract_frames(path: str, times: list[float], out_dir: str) -> list[str]:
    ffmpeg, _ = ffmpeg_tools()
    if not ffmpeg:
        return []
    os.makedirs(out_dir, exist_ok=True)
    out = []
    for k, t in enumerate(times):
        p = os.path.join(out_dir, f"frame_{k:02d}.jpg")
        try:
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{max(0, t):.2f}", "-i", path, "-frames:v", "1",
                            "-vf", "scale=512:-2", "-q:v", "5", p], capture_output=True, timeout=60)
            if os.path.exists(p):
                out.append(p)
        except Exception:
            pass
    return out


def b64file(path: str) -> tuple[str, str]:
    ext = os.path.splitext(path)[1].lower()
    mt = {".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "image/jpeg")
    with open(path, "rb") as f:
        return mt, base64.standard_b64encode(f.read()).decode()


def document_text(data: bytes, filename: str, limit: int = 60_000) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            text = "\n".join((p.extract_text() or "") for p in reader.pages[:80])
        except Exception as exc:
            raise ContentError(f"Could not read PDF: {exc}")
    elif ext == ".docx":
        try:
            import zipfile
            xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf-8", errors="replace")
            paras = re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)
            text = "\n".join("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)) for p in paras)
            text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")
        except Exception as exc:
            raise ContentError(f"Could not read the Word document: {exc}")
    else:
        text = data.decode("utf-8", errors="replace")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:limit]
