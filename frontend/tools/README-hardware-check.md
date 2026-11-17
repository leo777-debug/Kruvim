# Kruvim physical-device diagnostic

This is a local-only diagnostic, not a deployed Kruvim website. It contains the same local file preparation code and does not send your files or extracted content to Kruvim or an AI provider. A first speech test on a device reporting at least 8 GB downloads public Whisper weights from Hugging Face (about 40 MB). Runtime assets are included.

1. Extract the whole ZIP on the Windows laptop you want to check. Keep its folders together.
2. From that folder, run `powershell -NoProfile -ExecutionPolicy Bypass -File .\Start-hardware-check.ps1`. The execution-policy override applies only to this process. The script starts a static server listening only on this laptop's loopback address; it accepts no uploads.
3. Open `http://127.0.0.1:5188/hardware-check/index.html` in Chrome or Edge.
4. Choose synthetic files from the included `fixtures` directory, run the checks, then save the diagnostic JSON report. Repeat in the other browser if available. Stop the PowerShell server with Ctrl+C when finished.

For **under 8 GB or unknown browser RAM**, start with `brief.pdf`, `brief.docx`, `slide-red.png`, `slide-blue.jpg`, and the two small WebP files. You can also choose `large-video.mp4` and `large-audio.wav`: the supplied transcript is used in conservative mode, with no speech model download. Video frame extraction is limited to 1080p and four resized frames. The large PDF and PNG intentionally exceed conservative limits; their rejection is expected, not a parser failure.

For the **standard profile**, choose the large PDF, PNG, WAV and MP4. Speech is actually recognized locally; the supplied-transcript box is used only in conservative mode. Recognition errors and silence markers are possible. This diagnostic does not exercise cloud analysis or simulation.

The report records physical RAM as reported by Windows `GlobalMemoryStatusEx`, browser version, selected file names/sizes, processing times, result counts and errors. It excludes document text, transcripts and image data. Use the supplied synthetic fixtures to avoid putting private filenames in a report you share. A completed run demonstrates only these files on this device; it is not a guarantee for every client laptop or memory-pressure condition. RAM values from the browser may be rounded or missing; the Windows hardware value is reported separately.

Below 2 GB reported browser RAM, local file preparation is disabled. The main Kruvim website can still accept pasted text/transcripts; this file-processing diagnostic will report the safety refusal. If a browser process is killed by the OS, note which file was processing and repeat with a smaller file. The unsaved report may be lost; JavaScript cannot reliably recover a killed process.
