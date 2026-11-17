# Browser-local content preparation

Kruvim remains a hosted website. Content files selected in the test editor and background documents selected on project pages are prepared on the user's laptop. Selecting or preparing a file does not create an upload, signed storage URL, multipart request, or cloud object. The browser never invokes the Web Speech API, which may use remote speech recognition.

Before sending, a review dialog explains the boundary and displays editable extracted text/subtitles and removable resized images. Confirming sends those derived values, titles/descriptions, filename metadata for background documents, image order/timestamps, and duration to the existing backend. Cloud AI analysis, audience simulation, and saved results remain cloud services. Derived content is saved under the existing project/workspace/library visibility rules. This is not end-to-end encryption or local AI simulation. Provider credentials stay in the existing backend provider configuration; no provider credential is used by the local workers.

No billing, storage subscription, bucket limit, or production deployment was changed. Legacy server upload endpoints and previously stored attachments remain compatible with old clients. The updated content/background-document UI has no file-upload helper or fallback. Public URL imports and unrelated survey/dataset ingestion retain their existing behavior; they are separate from selecting local content files.

## Inspected flows and implementation

- Previously, `uploadAsset()` authorized a signed Supabase transfer, sent the original file, and finalized an attachment. Both simulation variants, carousel slides, and project/seed documents used it. Local-development fallback also posted originals as multipart data. Those calls and the frontend helper have been removed from this workflow.
- Previously, the backend content card loaded original assets, extracted document text, optionally used faster-whisper, and used FFmpeg for frames. Existing compatibility paths remain, but browser-prepared variants supply validated `local_media` JPEGs and duration plus text/SRT directly.
- PDF.js performs parsing in its own worker, one page at a time. Text files are read incrementally with a strict UTF-8 decoder. DOCX decompression runs in a disposable worker and bounds `word/document.xml` expansion; paragraph text is parsed without injecting HTML. Reading order, PDF page labels, and paragraph boundaries are retained where the document parser exposes them.
- Audio/video speech uses quantized multilingual `Xenova/whisper-tiny` through Transformers.js/ONNX WebAssembly in a worker. It resamples natively to mono 16 kHz and sends one 30-second sample buffer at a time to the worker using transferable buffers. Offset SRT timestamps survive the existing timed-segment/card pipeline. The model may misrecognize words, hallucinate silence, or lose words at chunk boundaries; the editable review is necessary.
- Native `decodeAudioData` requires the complete compressed audio buffer. This path is bounded, not fully streaming. Video frame extraction uses a local blob URL and sequential native seeks, with at most eight sparse frames. Image dimensions are checked from a bounded header read before native bitmap allocation. JPEG/PNG/WebP images and selected video frames are re-encoded to JPEG at a maximum 1024-pixel standard / 768-pixel conservative edge; canvas re-encoding discards original image metadata.
- A/B variants are prepared independently. Carousel images are processed sequentially in the user's order; old attachments and new slides retain their ordering. Derived media survives draft reload/edit. The backend vision adapter receives only selected JPEGs and their ordered timestamps alongside textual segments.
- Background documents use `/projects/{id}/assets/extracted-text`: only reviewed text and the filename are saved in the database. No object-storage object is created. Stored context continues through the existing seed-document knowledge-graph flow.

## Formats, limits, and hardware

There is no 8 GB minimum for using Kruvim. Browsers reporting under 8 GB, or no RAM estimate, use a conservative profile: 2 MiB text, 8 MiB PDF/images, 4 MiB DOCX, 1 MiB document XML, 40 PDF pages, 12-megapixel source images, and 768-pixel outputs. Video up to 128 MiB and 1080p can supply at most four frames when a transcript is provided. Automatic speech and its model download are disabled in this profile. Below 2 GB reported browser RAM, file preparation is refused and users can paste text/transcripts. These are capability policies, not physical hardware certification.

The table below describes the standard profile, enabled when the browser reports at least 8 GB.

Supported and exercised desktop targets are Chrome 157 and Edge 157 on Windows. Web Workers, WebAssembly, Canvas, native media decoding, and secure website/localhost access are needed. Safari, Firefox, mobile devices, other operating systems and older browser releases have not been qualified. Missing capabilities and codecs produce explicit errors and transcript/text alternatives.

| Input | Local safety ceiling | Important limits |
| --- | --- | --- |
| UTF-8 TXT, MD, CSV, JSON | 128 MiB source | 60,000 extracted characters; oversized content fails rather than silently truncating |
| Text PDF | 64 MiB, 200 pages | 60,000 extracted characters; no scanned-image OCR or password UI |
| DOCX | 16 MiB source | 4 MiB document XML expansion, 60,000 characters; paragraphs only, no layout fidelity/embedded-image analysis |
| PNG, JPEG, WebP | 64 MiB, 40 megapixels | Maximum 1024-pixel output edge, 350,000 data-URL characters per JPEG |
| Browser-decodable audio/video | 128 MiB source | Tested WAV PCM and H.264/AAC MP4; codec support is browser-dependent |
| Automatic speech | 10-minute duration ceiling **and** 128 MiB estimated decoded stereo audio ceiling | The memory calculation makes the practical duration lower than 10 minutes; actual decoded-buffer size is also checked. Larger/longer media needs a pasted transcript. |
| Images sent per variant | 10 slides; video samples at most 8 | 1.5 MB combined image data per variant; 3.5 MB complete JSON request ceiling |

These are conservative safety ceilings, not tested throughput promises at every boundary. The largest files exercised are listed in the verification report. Browser RAM estimates may be rounded or absent; unknown RAM selects the conservative profile. The test machine had approximately 40 GiB, so physical 4 GB/8 GB devices have not been qualified. The conservative profile passed browser-process-tree tests with a 1 GiB committed-memory limit; the standard speech profile passed a 2 GiB limit. These limits exclude the operating system and other applications and do not establish physical-hardware guarantees. Native codec decoders can temporarily consume additional memory; close other tabs and split files if necessary. An OS-level memory kill cannot always be caught by JavaScript.

## Downloads and offline behavior

First speech use downloads approximately 40.85 MB of quantized encoder/decoder weights, plus tokenizer/configuration files, from Hugging Face. The ONNX runtime is packaged with Kruvim (approximately 21.6 MB WASM plus its JavaScript module). No file content accompanies these GET requests; hosting services still see ordinary network metadata such as IP addresses and requested asset/model names.

Transformers.js caches model assets in the browser. Workers are terminated after each preparation so inference memory can be reclaimed; cached model files deliberately remain for reuse. Clearing browser site data or cache eviction removes them. A cached-model run is tested with all external HTTPS requests blocked while Kruvim's local server still serves runtime assets. This verifies independence from model-hosting services after caching. It does **not** verify a completely offline website: loading/authenticating Kruvim and cloud analysis require a connection. There is no offline-installable PWA/service-worker guarantee; a missing page/runtime asset can prevent local work when the whole device is offline.

## Progress, cancellation, cleanup, and failures

The UI reports document pages/characters, model-download progress, transcription chunks, and frame counts, and offers cancellation during local preparation. Cancelling prevents a review result or file-content submission. Workers are terminated, media elements unloaded, object URLs revoked, audio contexts closed, bitmap handles closed, and canvases cleared. Discarding review drops derived content; navigating away aborts active preparation. Original selected files are retained as browser `File` handles until deselected/navigation, not copied into cloud storage.

Native audio decode and file-buffer reads have no browser abort primitive. The UI rejects cancellation immediately and discards the eventual result; the browser may briefly finish native work in the background. Hard browser/OS allocation failures remain a limitation. Failed decoding, missing model downloads, malformed documents, empty/scanned PDFs, unsupported formats, or size/memory guards never fall back to uploading originals. The user can remove the file and paste plain text or SRT/VTT, use a smaller excerpt, run local OCR, or convert/split media with a local application.

See [paid-provider and conservative-device follow-up](browser-local-followup-2026-11-17.md) and [initial verification report](browser-local-verification-2026-11-17.md) for actual evidence and unverified cases.
