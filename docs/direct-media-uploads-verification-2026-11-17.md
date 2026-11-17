# Direct uploads and media processing

Implemented locally on `fix/direct-media-uploads-20261117`, based on production commit `496572102660158ee54c84997b5e7b7d780a11d4`. No production deployment, billing change, bucket update, or paid model request was performed.

## Upload flow

Simulation uploads (including A/B versions, images/carousels and research seeds) and project research uploads now use the same client helper:

1. Authorize with a small JSON request to `POST /projects/{project_id}/assets/upload`.
2. Transfer the raw file from the browser to a scoped private Supabase signed upload URL or an S3-compatible presigned URL.
3. Finalize with a small JSON request to `POST /projects/{project_id}/assets/complete`.

The authorization receipt binds the workspace, project, user, object key, asset ID, filename, size and MIME type for two hours. Finalization rechecks project access and storage metadata. It downloads documents for text extraction but does not download video/audio/image bytes. Asset IDs make finalization retries idempotent, including concurrent retries. No service credentials reach the client, and the storage request does not carry the application's authorization or workspace headers. Local development retains its multipart flow; hosted execution cannot select that fallback. S3 deployments must allow browser PUT/CORS requests including `Content-Type` and `If-None-Match`.

The app's configured maximum remains 500 MiB. The Supabase adapter also checks the bucket's actual limit before signing. Storage transfers use a standard signed PUT; interrupted transfers restart, while interrupted finalization retries without transferring the file again. Resumable TUS transfers are not implemented.

## Production storage finding

Read-only Supabase queries on 17 November 2026 confirmed that ANE (`jrdgxbdglmpynbyfmamf`) is healthy, the `kruvim-data` bucket is private, and its `file_size_limit` is **52,428,800 bytes (50 MiB)**. Its organization reports `plan: free`, `tier: tier_free`.

Direct uploads bypass [Vercel's 4.5 MB function payload limit](https://vercel.com/docs/functions/limitations). They do not raise the storage account's limit. A genuine 500 MiB production transfer still requires storage that permits that size, followed by a matching bucket limit. No upgrade was requested or performed. See [Supabase upload limits](https://supabase.com/docs/guides/storage/uploads/file-limits).

## Media changes and evidence

- A supplied video/audio script now bypasses automatic transcription, as an explicit transcript already did.
- Empty speech and transcription/model initialization failures produce actionable transcript/setup errors.
- Missing video tooling or incomplete frame extraction is disclosed in content-card notes.
- Partial frame extraction retains each frame's correct segment index.
- Cards record `visual_analysis.status` and attached image count. Dry runs and text-only models never claim visual analysis.

The deployed dependency manifests do not install optional faster-whisper; Vercel does not gain FFmpeg/ffprobe from the Docker image. Consequently this change **does not certify automatic transcription or video frame extraction in production**. Those require a processing worker with the tools installed, or supplied transcripts for text-based analysis. Images can reach a configured vision model without FFmpeg. No live model's ability to interpret images was evaluated here.

## Checks

| Check | Result and scope |
| --- | --- |
| Backend upload, media, link and dry workflow suites | 19 passed. Includes 500 MiB metadata authorization/finalization with mocked storage; no actual 500 MiB file transfer. |
| Browser upload tests | 2 passed in Microsoft Edge. A real browser sent 6,000,000 bytes to an intercepted cross-origin storage request; app payloads stayed below 1 KiB. Finalization retried once without a second file transfer. Storage failure prevented completion. Storage itself was simulated. |
| FFmpeg integration | Generated a real two-second video, probed duration and extracted a real JPEG frame. Verified JPEG bytes reached the vision-model request via the real OpenAI-compatible adapter with simulated HTTP responses. |
| Transcription adapter | Simulated faster-whisper segments and empty results; verified missing-package errors and supplied-script behavior. No real speech-recognition inference ran. |
| Python lint | Ruff passed for all changed backend files and tests. |
| Frontend | Typecheck and production build passed. |

Browser checks used shared local dependencies through a directory junction, which caused a Vite font-serving warning. No visual styling verification is claimed. A broader repository suite was not run.

Before calling this production-verified, deploy frontend and backend together, exercise a real signed storage transfer with an authenticated ordinary user, confirm the storage account and bucket support the required file size, and run speech/video/vision fixtures on the actual processing host. Expired/abandoned uploads can leave unreferenced objects; an operational retention policy is still needed for those objects.

Reproduce from this worktree:

```powershell
cd backend
python -m pytest tests/test_direct_uploads.py tests/test_media_processing.py tests/test_content_links.py tests/test_e2e_dry.py -q
cd ../frontend
npm run typecheck
npm run build
npm exec playwright test -- --config playwright.uploads.config.ts
```
