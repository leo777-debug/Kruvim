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

The release is based on live commit `f828521`, preserving its newer library and
data-feed fixes. Only the focused frontend patch, its tests, and this note are added.
