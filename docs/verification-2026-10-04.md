# Verification of the four click-through corrections

The interface remains English-only. No schema changes were required: readable citations are derived from existing graph/report records, and news-tone provenance uses the existing signal payload. Blank API-key defaults, dry-run behavior and OpenAI-compatible local-model support remain covered by the suite.

## Reproduction and root causes

Twenty full-suite runs used randomized orders with seeds 100–119, each in a fresh process. Only one complete baseline suite passed; `test_documents_autopilot_recurring_and_monitoring` failed in 13 of these runs. Logs reproduced both a missing competitor alert (`unread == 0`) and quota failures caused by another test's workspace changes. Sharing checks also encountered rate-limit state left by earlier tests.

The session-scoped workspace/database allowed plan, balance and rate-limit mutations to reach later tests. The simulation's completed status was committed before its job finished writing alerts and audience memory, so status polling was insufficient. The automatic scheduler also used the real clock while tests invoked recurring work themselves.

Each test now receives clean tables, its own workspace and disk directory, and reset event, queue, population and rate-limit state. Inherited database/provider settings are replaced with a disposable SQLite/dry-run configuration before imports. Local queue draining awaits chained jobs and side effects before assertions and teardown. Scheduled checks use one injectable time, and recurring tests assert the exact next due date and idempotence. Scheduled checks are explicitly invoked in tests; application shutdown awaits cancellation in development.

## Final result

**20 consecutive shuffled full-suite runs passed after the fix**, with seeds 200–219. Each run passed all 57 tests: 1,140 test executions in total. Runs used separate processes, with three processes running concurrently and each suite running its tests sequentially. Seed summaries and timings are retained in [full-suite-repeat-2026-10-04.json](full-suite-repeat-2026-10-04.json).

Ruff, `tsc --noEmit`, the agent-selection regression check and the Vite production build passed. Feature/browser/export checks are described below. These local results do not certify the external services listed under verification limits.

## Feature checks

- Citation tests cover section numbering, duplicate removal, source resolution, readable labels, tenant scoping, legacy reports, superscripts, raw provenance in private APIs/JSON, and absence of raw IDs in public payloads and PDF/Word/Markdown downloads.
- Interview selection checks cover first selection, retaining an existing selection, filtering it out, empty lists and invalid links. Browser checks at 390px cover automatic selection, URL refresh, search changes and the empty state.
- News-tone fixtures cover GDELT's histogram contract, recorded connection timeouts, rate-limit diagnostics, regional English/Arabic headlines, all fallback steps, aged labels, model failures/cache, workspace isolation, provenance, weights, and model credit reservation/refund.
- A disposable server completed a dry-run simulation with both UAE and Saudi headline fallbacks. Its private report and anonymous share had 13 rendered citations including the summary, with readable sources and no raw IDs. A citation opened its graph source. Method displayed both tone sources and their 0.5 confidence weights.
- The report and public share had no horizontal page overflow at 390px. All three PDF pages were visually reviewed. Word content, superscript formatting and embedded charts were checked through document structure; Markdown content and images were checked by tests.

## Reproduce the repeat check

From `backend`, run:

```text
python -m tools.repeat_suite --runs 20 --seed 200 --workers 3 --output data/repeat-after-fix
```

The tool runs independent full suites and retains seed-specific diagnostic logs plus a JSON summary in the ignored data directory. Three processes run concurrently; tests within each process run sequentially. `python -m pytest -q -p tools.shuffle_order --shuffle-seed=200` reproduces one order without an extra test-order dependency.

## Verification limits

GDELT's AE/SA requests timed out during live diagnosis, so successful live recovery could not be certified. Regional RSS searches were captured successfully; assertions use recorded fixtures and do not call live networks. Connected-model scoring uses protocol/stub coverage, not paid-model quality or an installed Ollama/GPU model. PostgreSQL/pgvector and Redis execution were not exercised in this local SQLite run. Word visual rendering was unavailable because the bundled LibreOffice runtime was unavailable.

## Sidebar navigation (item 5)

The navigation regression check passed for all 13 links against explicit JSX routes, excluding the catch-all redirect. It also checks the requested group/item order, unique destinations, tooltip descriptions, nested active paths, case/trailing-slash matching, administrator visibility, per-user preferences and invalid/unavailable browser storage. The existing agent-selection regression check passed. The full backend suite passed all 57 tests; Ruff, `tsc --noEmit` and the production Vite build passed.

Browser verification used the production build with a disposable SQLite/dry-run API server. Every destination opened and showed exactly one styled active item. The legacy `/audiences?scope=community#library` redirected to `/saved-audiences?scope=community#library`. A Saved audiences hover displayed its readable tooltip. The five groups rendered at desktop width and in a 390px drawer, without horizontal overflow. Mobile link selection closed the drawer; reopening highlighted Saved audiences. Collapses survived refresh and were shared between desktop and mobile. Signing in as a second user started with independent preferences and omitted Platform admin; returning to the platform administrator restored the first user's choices. Public accuracy rendered with active navigation when signed in and remained public with a sign-in link when logged out. No browser console errors were recorded.

This item changes no backend schema. Preferences are browser-local and do not sync across devices. Production deployment, other browsers and device-specific touch/screen-reader behavior were not exercised.
