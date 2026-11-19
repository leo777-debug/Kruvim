"""Generate real synthetic files for local-processing browser checks.

Needs reportlab, python-docx, Pillow and FFmpeg; System.Speech or Linux espeak.
The large files are deliberately outside the Git checkout. No user files/network
services are used. Noise bytes vary between runs, so exact compressed sizes vary.
"""
from pathlib import Path
import os
import subprocess

from docx import Document
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

destination = Path(__file__).resolve().parents[3] / "kruvim-local-processing-evidence" / "fixtures"
destination.mkdir(parents=True, exist_ok=True)
(destination.parent.parent / "kruvim-paid-local-followup-20261117").mkdir(parents=True, exist_ok=True)
voice_path = str(destination / "speech.wav").replace("'", "''")
if os.name == "nt":
    subprocess.run(["powershell", "-NoProfile", "-Command", "Add-Type -AssemblyName System.Speech; "
                "$localSynth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$localSynth.SetOutputToWaveFile('{voice_path}'); "
                "$localSynth.Speak('Kruvim keeps your original files on your laptop. You can review this transcript before sending text to the cloud. Try this simple breakfast recipe with oats and banana.'); "
                "$localSynth.Dispose();"], check=True)
else:
    subprocess.run(["espeak", "-w", str(destination / "speech.wav"),
                    "Kruvim keeps original files on your laptop. Review this transcript before sending text to the cloud. Try breakfast with oats and banana."], check=True)

(destination / "brief.md").write_text("# Context\nBrand guidelines: breakfast with oats and banana.", encoding="utf-8")
(destination / "broken.pdf").write_bytes(b"not a PDF")
c = canvas.Canvas(str(destination / "brief.pdf"))
c.drawString(72, 720, "Kruvim local PDF context: preserve this brief.")
c.showPage()
c.drawString(72, 720, "Page two: campaign targets breakfast recipes.")
c.save()
d = Document()
d.add_heading("Kruvim local document", 0)
d.add_paragraph("Brand guidelines: helpful recipes for busy people.")
d.save(destination / "brief.docx")
Image.new("RGB", (2400, 1600), "red").save(destination / "slide-red.png")
Image.new("RGB", (1600, 2400), "blue").save(destination / "slide-blue.jpg")
Image.new("RGB", (640, 480), "green").save(destination / "small-lossy.webp")
Image.new("RGB", (640, 480), "green").save(destination / "small-lossless.webp", lossless=True)
c = canvas.Canvas(str(destination / "forty-one-pages.pdf"))
for page in range(41):
    c.drawString(72, 720, f"Page {page + 1}")
    c.showPage()
c.save()
large_xml = Document()
large_xml.add_paragraph("A" * 1_100_000)
large_xml.save(destination / "large-xml.docx")

c = canvas.Canvas(str(destination / "large-brief.pdf"))
for i in range(2):
    image = Image.frombytes("RGB", (3200, 2400), os.urandom(3200 * 2400 * 3))
    c.drawImage(ImageReader(image), 20, 180, width=560, height=420)
    c.drawString(72, 740, f"Kruvim large local document page {i + 1}: preserve the complete context.")
    c.showPage()
c.save()
Image.frombytes("RGB", (4800, 4000), os.urandom(4800 * 4000 * 3)).save(destination / "large-image.png")

subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30",
                "-i", str(destination / "speech.wav"), "-t", "20", "-c:v", "libx264", "-preset", "ultrafast",
                "-b:v", "30M", "-minrate", "30M", "-maxrate", "30M", "-bufsize", "60M", "-x264-params", "nal-hrd=cbr:force-cfr=1",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(destination / "large-video.mp4")], check=True)
subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(destination / "speech.wav"), "-af", "apad",
                "-t", "75", "-ar", "96000", "-ac", "2", "-c:a", "pcm_s32le", str(destination / "large-audio.wav")], check=True)
for item in destination.iterdir():
    print(item.name, item.stat().st_size)
