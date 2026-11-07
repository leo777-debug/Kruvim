# Page loading — 7 November 2026

The frontend entry point downloaded charts and Markdown through shared helpers
placed in manually assigned vendor chunks. Project simulation tables also imported
status labels from the full simulation page, pulling in its graph and report tools.
Every restored session then waited for `/auth/me` after `/auth/refresh`, although
refresh already returns the current user and workspaces.

Changes:

- Allow automatic feature dependency splitting, retaining the React vendor chunk.
- Move shared simulation status labels into a small standalone module.
- Restore the session with a single refresh request and load the requested page's
  code concurrently. Access tokens remain in memory; route authorization is unchanged.
- Preload destination code on navigation hover/focus. This does not fetch workspace data.
- Put a Suspense boundary around the page outlet so the shell remains available.

Production build measurements, summing each page's full static JavaScript import
closure (excluding dynamic imports, CSS and fonts):

| Page | Before raw bytes | After raw bytes | Before gzip bytes | After gzip bytes |
| --- | ---: | ---: | ---: | ---: |
| Entry | 1,025,927 | 462,723 | 307,695 | 149,324 |
| Home | 1,064,070 | 500,729 | 321,083 | 162,646 |
| Projects | 1,029,571 | 466,302 | 309,313 | 150,904 |
| Project detail | 1,380,885 | 885,897 | 419,750 | 267,170 |

The entry reduction is 55% raw and 51% gzip. These are build-size measurements,
not a claim of the same percentage improvement in hosted response time.

Validation:

- `npm run build -- --manifest`: TypeScript and production build pass.
- `node tools/check-page-bundles.mjs`: static dependency budgets pass.
- `npm run test:navigation`: all 17 real navigation destinations pass.
- `playwright.loading.config.ts` uses a production preview and a disposable SQLite
  backend. Desktop and 390px mobile checks cover real login/refresh, no redundant
  account fetch, navigation during a deliberately delayed page chunk, and library
  save/edit/CSV import/reload. No production accounts, research or provider calls
  are used by these browser tests.

The frontend release is based on live commit `f828521`, preserving its newer
library and data-feed fixes. Commit `842aa41` adds the frontend patch and tests.

## Hosted API follow-up

Live logs also showed signed-in requests spending 2–3.4 seconds in the API.
Supabase reports database region `eu-central-1` (Frankfurt); the previous service
had no explicit regional placement. Commit `f2c8213` configures the backend
function for `fra1` in the owning service and backend configuration. The local
release preparation script preserves that placement in future releases.

A temporary account measured the same authenticated endpoints before and after
the configuration deployment, from the same client, without fetching any existing
user's data. All responses returned HTTP 200:

| Request | Before (two calls), ms | After (three calls), ms |
| --- | --- | --- |
| Projects | 2,552; 2,165 | 1,206; 704; 258 |
| Runs | 2,828; 2,202 | 762; 254; 267 |
| Account | 1,798; 1,376 | 443; 243; 224 |

These sample request timings include client network overhead; the test workspace
was empty. They are not a guarantee for every page or an existing large workspace.
The final warm project/run handlers logged 59–83 ms internally.

Production deployment `dpl_CbocTmWhhBDMPgKABTCsdNe2CFgf` reached READY and owns
`kruvim-lp.vercel.app`. The live HTML preloads only the React vendor chunk, and
the live entry contains the new page-loading boundary. The temporary account
was signed out and deleted with its temporary workspace; database checks confirmed
both were absent. No research, simulation, provider or billing records from
existing workspaces were modified.

## Blank-screen follow-up

After a report of a white screen, a headless Edge browser exercised the live Home,
My tests, Data pool, Data library, Settings, Help and public homepage. All rendered
with no page errors in a fresh session. The temporary account was signed out and
removed with its workspace; deletion was verified.

The application had no React error boundary and no Vite failed-chunk recovery.
An already-open tab can request old lazy-loaded filenames after deployment.
That is a likely explanation for the report; the exact failing user tab was not
available to confirm it.

- Handle Vite preload errors by refreshing the asset map once, keeping the stored
  session. A session-storage timestamp prevents a reload loop.
- Show a clear Reload Kruvim control for persistent page/render failures.
- Browser regression checks inject a real HTTP 404 for a page chunk, verify one
  automatic reload and successful authenticated rendering, and check persistent
  failures display recovery controls. Both desktop and mobile are covered.
- TypeScript, production build, bundle budgets and navigation checks pass.
- Initial browser run passed nine checks; its tenth reached the recovered page
  but incorrectly expected a desktop-only Sign out button on mobile. The check
  was corrected to verify the authenticated library controls instead, then the
  missing-chunk cases were rerun on both viewports.
