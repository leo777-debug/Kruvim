# Paid cloud inference and lower-memory follow-up

This follows the initial `523a3f8` implementation. Deployment remains on hold until the user explicitly confirms it. No billing, storage subscription, bucket limit or existing provider configuration was changed.

## Client laptops do not need an 8 GB minimum to use Kruvim

The heavy operation is browser speech inference. On this approximately 40 GiB Windows host, the standard workflow passed a **2 GiB OS-enforced aggregate process-tree commit limit**, but peaked near that limit. That does not qualify a physical 4 GB/8 GB laptop, where Windows, other applications and driver/shared memory also need RAM.

The implementation now chooses a conservative mode when the browser reports under 8 GB **or does not report RAM**. It does not infer available memory from a misleading JavaScript-heap-only measurement.

| Capability | Standard: reported RAM ≥8 GB | Conservative: 2–4 GB or RAM unknown |
| --- | --- | --- |
| Automatic speech recognition | Allowed within duration/decoded-buffer ceilings | Disabled before decoding or downloading a model; paste text/SRT/VTT |
| PDF | 64 MiB / 200 pages | 8 MiB / 40 pages |
| DOCX / expanded XML | 16 MiB / 4 MiB | 4 MiB / 1 MiB |
| Text source | 128 MiB | 2 MiB |
| Image source | 64 MiB / 40 megapixels | 8 MiB / 12 megapixels |
| Resized image edge | 1024 pixels | 768 pixels |
| Video with supplied transcript | 128 MiB, up to eight frames | 128 MiB / 1080p, up to four frames |

Both profiles reject extracted text beyond 60,000 characters instead of silently truncating it. The existing cloud request bounds remain. Below 2 GB reported RAM, file preparation is disabled and users are directed to pasted text/transcripts. The website's cloud analysis remains available for those manual inputs. No fallback uploads original files.

Image dimensions are now checked from a bounded header read **before** native bitmap allocation. JPEG, PNG, lossy WebP and lossless WebP were exercised. A forged oversized PNG header was rejected without invoking the bitmap decoder.

### Memory-limit evidence, not physical hardware certification

The Windows job includes the newly launched Node test controller and its isolated browser descendants. It does not modify host RAM, boot settings or existing browser processes. These are committed-memory process limits, not simulations of the entire OS or measurements of every shared allocation. [Windows job limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information), [job memory accounting](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information).

| Browser / policy | Enforced aggregate limit | Peak recorded committed memory | Result |
| --- | ---: | ---: | --- |
| Edge / standard speech | 2 GiB | 1,972,408,320 bytes | Passed large PDF, PNG, automatic WAV/MP4 speech and frames |
| Chrome / standard speech | 2 GiB | 1,970,642,944 bytes | Passed the same matrix |
| Edge / conservative | 1 GiB | 760,033,280 bytes | Passed ten allowed document/image/media checks |
| Chrome / conservative | 1 GiB | 807,903,232 bytes | Passed the same matrix |

The conservative matrix includes an **8,254,274-byte PDF**, a **7,214,684-byte / 12-megapixel JPEG**, DOCX, PNG, JPEG, both WebP variants, the **57.6 MB WAV** with a supplied transcript, and frames from the **74.6 MB 1080p MP4** with a supplied transcript. Both browsers recorded zero content requests during these local preparations. Larger PDFs/images, overlong PDFs/XML and automatic speech were deliberately refused under conservative policy.

Browser tests also verified the real website's transcript-first flow: automatic speech is refused on a reported 4 GB device, no model is downloaded, a supplied transcript is reviewed and saved, and no audio attachment is transferred. Reported-4-GB and unknown-RAM tests are capability overrides and are **not physical 4 GB tests**.

**Physical 4 GB/8 GB client hardware remains unqualified.** The local-only diagnostic ZIP includes fixtures, runtime assets, a Windows loopback-only launcher, and a report exporter that records physical RAM through `GlobalMemoryStatusEx`. Its launcher and both profiles were tested on the current 40 GiB host in Chrome/Edge. The artifact can be run on an actual client laptop without uploading content; a successful report on that laptop is needed to claim that physical device was verified. A killed browser process may lose unsaved diagnostic results.

## Live cloud provider checks

The existing Mistral credential remained encrypted on the backend. It was copied server-side into disposable test-workspace configurations, never exported as plaintext or sent to a browser. The original workspace's vision-model field is blank and was left unchanged. The disposable configuration used `ministral-3b-latest` for text/report and vision. Actual selected-frame output described the visible grid/test pattern, and the application recorded vision analysis rather than a dry-run substitute.

The existing key reports **two requests per minute**, so genuine simulations/reports take much longer than local preparation. The completed small run (10 voice agents, 20 crowd agents, one simulated hour) took approximately 29 minutes including setup; this is not a latency guarantee for larger presets. These checks consumed the existing provider allowance; no provider plan was upgraded. Configured prices were absent, so no invoice/monetary cost is claimed.

Scope matters: the user has not approved deployment of the new branch. Live checks therefore used the **currently deployed API's compatibility path**, with only browser-derived text and re-encoded selected JPEGs. That old path temporarily stores the selected JPEGs as attachments. It never received original documents, images or raw audio/video. The new branch's storage-free JSON path was separately exercised against its local backend and in the compiled `/app/` browser tests. This is not a claim that the undeployed API has already been exercised on production.

| Live check | Observed result |
| --- | --- |
| Provider connection | Genuine Mistral response; request-rate limit disclosed |
| Selected video frame → vision/card/graph | Four successful model calls, zero failed calls; `visual_analysis.status=analysed`, one image |
| Paid A/B graph and environment | Genuine text/vision calls; zero recorded failures |
| Paid A/B simulation | Completed; `fallback_calls=0`, `failed_provider_calls=0` |
| First A/B analyst report | **Not a pass.** Test timeout/cleanup interrupted the unfinished report. |
| Retried single-variant paid simulation | Completed, 14 simulation model calls, no provider failures/fallbacks |
| Retried analyst report | **Passed:** status `done`, 12,376 characters of actual model-written Markdown, model `ministral-3b-latest`, no report error. |

### Errors found and corrected

- The review did not explicitly explain that a blank vision-model configuration means images cannot be analyzed. It now warns before sending that images will be saved but not analyzed without a connected vision model.
- The initial test timeout was too short for this key's two-request/minute limit. Its cleanup deleted a project while the analyst report was unfinished; the report job subsequently recorded `AttributeError`. That interrupted report is retained as failure evidence and is not counted as a successful full pipeline. The verification runner now preserves progress snapshots, retains unfinished projects, refreshes expired sessions and allows a longer bounded completion window.
- The project-deletion API allowed completed simulations with **active analyst reports** to be deleted. The branch now rejects deletion while graph/environment/simulation work or a queued/running report is active. Four regression cases verify the rejection and successful deletion after work finishes. This guard is not yet deployed.
- Vite's diagnostic HTML changes could reload unrelated development-test pages. The diagnostic directory is now excluded from the main app's development watcher; affected extraction checks passed after rerun with stable sources.

## Verification and reproducibility

The updated focused backend selection passed **35 tests**. The changed browser workflow passed the ten standard scenarios, six conservative-policy/UI scenarios, and two compiled-production matrices across Chrome and Edge. Eight additional report-continuation, citation, sharing and provider-pacing tests also passed (**43 backend tests total across the focused selections**). The live retry completed with 52 successful model calls (4 graph, 1 environment, 14 simulation, 33 report), zero recorded failed calls at every stage, and zero deterministic fallbacks. Its five-section analyst report was fetched and checked for real Markdown output, not a dry-run marker. Failed/interrupted attempts are not counted as passes.

Evidence is in sibling `../kruvim-paid-local-followup-20261117/`: `paid-ab-interrupted-report.json`, `paid-evidence.json`, `*-job.json`, `*-browser.json`, `*-conservative-*.json`, `*-conservative-ui.json`, and portable-diagnostic reports. Auth response bodies, authorization headers, plaintext keys and signed transfer URLs are excluded. Only synthetic fixture content was used.

Memory checks (Vite verification server running on port 5186), from `frontend/`:

```powershell
python tools/run-memory-limited.py msedge 1 conservative
python tools/run-memory-limited.py chrome 1 conservative
python tools/run-memory-limited.py msedge 2 standard
python tools/run-memory-limited.py chrome 2 standard
npx playwright test --config playwright.conservative.config.ts
```

The live runner requires an operator to copy the existing encrypted provider into the exact disposable organization emitted by `ready.json`, then signal `continue`. Its backend-only credentials stay in memory/server-side storage. It is a controlled verification fixture, not a customer flow or permission to modify an existing workspace. Do not signal continuation until the provider-copy operation succeeds. Never delete an unfinished report fixture to force a test to end.

After the live checks, both test projects and all selected-image objects were removed, all three disposable test users were disabled, all their refresh sessions were revoked, and all temporary encrypted-provider copies were deleted. Final database checks confirmed zero active test users/sessions, zero provider copies, zero test projects and zero test storage objects. The original provider configuration remains present with its original blank vision field. Disabled accounts and audit history remain for traceability.

No release is approved by this report. Deployment requires the user's explicit confirmation, with the physical-device limitation and hosted-compatibility test scope understood.
