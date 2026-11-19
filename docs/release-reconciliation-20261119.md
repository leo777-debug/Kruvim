# Reconciled release — 19 November 2026

This branch, `release/reconciled-20261119`, is the release candidate. `RELEASE.json`
identifies the project, baseline, required schema and worker tiers. The older launch
checklist is historical backlog; it is not evidence that current checks pass.
Terms & Conditions and privacy policy remain deferred until last.

## Source reconciliation

The authoritative baseline is production commit
`8e9aab50557ee114447c2c5240bb7fded43a7205`, deployment
`dpl_BKRRy234dq2AsMomDer6Tpjjq1Qu`, project `kruvim-lp` in team
`team_wCW1Fz8EiXYTLsgKxcNFaYmf`. Production is served at
`https://kruvim-lp.vercel.app`. Vercel recorded that build as READY, but public
probes during this review returned `402 DEPLOYMENT_DISABLED`. An unpause request
did not resolve that provider response. READY alone does not establish availability.

The candidate combines the deployed lineage with:

- Local media preparation and lower-memory handling through `b16776d`.
- Account recovery, verification and shared authentication rate limits through
  `894d0f2` (account-security implementation `5282a95`).
- Durable job outbox, delivery deduplication, interrupted-job fencing and billing
  lock ordering through `d927dcc`.
- The background release's previously uncommitted external-worker requirement,
  separate maintenance queue, readiness checks and UTC scheduler.
- Recovery verification and the operational review from the main workspace.
- Integration fixes made on this branch and recorded below.

The main `Kruvim` checkout is based on older commit `f064a38` and contains substantial
uncommitted experiments. It is **not** a deployable substitute for this branch.
OASIS integration, the `0020` billing-seat migration and associated model changes,
and benchmark scripts in that checkout are excluded from this candidate. They are
preserved in the original checkout for a separately reviewed feature release.
The existing public upload fixes and local media preparation are retained here.

## Database reconciliation

Read-only production checks found revision `0019`, no `billing_seats`, no
`account_tokens`, `mail_outbox` or `rate_counters`, and no `auth_version` or
`email_verified_at` columns. Existing cloud jobs were 84 done and 3 error, with
no pending/running rows at the time checked. Do not replay error jobs automatically.

This release has **one head: `0021`, descending directly from `0019`**. It does
not include the separate `0020` seat feature. Never stamp a database to bypass
missing DDL. The upgrade is additive; it introduces authentication fields and
security tables. Generated SQL is in `release-upgrade-0019-0021.sql` and
`release-rollback-0021-0019.sql`; use Alembic against a verified schema for a real
cutover. These SQL files are unqualified and must never be run with an unchecked
search path.

PostgreSQL round-trip evidence: the exact generated upgrade and downgrade ran
`0019 → 0021 → 0019 → 0021` against a synthetic user in a new isolated schema,
inside a transaction that was rolled back. Assertions verified the original user
and password hash, the auth-version default, revision transitions and RLS on all
three security tables. The schema was absent afterward and the production revision
remained `0019`. This validates the migration delta, not a production backup restore
or every historical PostgreSQL migration.

## Integration fixes

- Keep SMTP outbox delivery as its own one-minute maintenance job. The worker
  refactor otherwise removed account recovery's periodic retry path.
- Preserve archived regional snapshots as a separate maintenance job. There are
  nine scheduled jobs after combining snapshot maintenance and mail dispatch.
- Health responses identify the build commit. Hosted readiness rejects a schema
  mismatch and requires workload, connector and maintenance worker heartbeats
  namespaced to the API's exact commit; older workers cannot satisfy readiness.
- Recovery verification distinguishes stored uploads from locally extracted text
  assets, which intentionally have no object key. It hashes both representations.
- Browser login selectors use an exact Password label so they do not also match
  the Save password checkbox.
- Vite emits the manifest consumed by the existing page-bundle budget check.
- Ruff issues in retained app/test/verification files were fixed.
- Restore workload/connector worker health checks and add the missing one-shot
  migration service. API and workers wait for migration completion; API replicas
  no longer race each other to apply DDL at startup. Compose configuration validates.
- Update stale tests to check both platform-admin authorization and cross-tenant
  upload isolation, and per-call accounting rather than obsolete upfront credits.
- Correct SQLite drift checking for the graph/memory vector indexes that are
  intentionally created only by PostgreSQL migrations. PostgreSQL checks stay enabled.
- Make media fixture generation usable on Windows and Linux, and run media and
  built-chunk checks with their dedicated browser/server configurations.
- Delay automatic chunk-recovery reload until an active rotating refresh response
  is saved. A deterministic browser case holds that response after the server has
  rotated it, preventing the reproduced mobile sign-out race. Use separate trace
  directories for independent browser suites.
- Restore functional ESLint commands/configuration for the app and Next.js landing.
- CI now runs on release branches and includes browser, landing, bundle-budget
  and old/new application rollback checks. Four isolated pytest processes have
  separate temporary databases and are scheduled by test file.

## Validation record

Final local test results are recorded below. Logs remain in the
local ignored `release-*.log` files; do not publish private diagnostic logs or traces.

- App TypeScript and production Vite build: passed, including manifest generation.
- Static bundle gzip budgets after the authentication recovery fix: entry 151,031
  bytes; new-test page 172,346 bytes; projects 152,613 bytes; all below the existing
  190,000-byte threshold.
- Navigation, agent selection and re-test logic: passed.
- App and landing dependency audits: **zero vulnerabilities** after compatible
  updates, including Next.js 16.4.6 and the patched TypeScript ESLint parser.
- Ruff across app, tests, scripts, migrations and tools: passed.
- Full backend rerun: **269 passed**. All 21 focused regressions passed; the final
  18-test worker/readiness run also passed, including the additional regression
  rejecting workers from another commit.
- Core browser coverage: 34 passed and 2 paid-mode skips in the full desktop/mobile
  run; two artifact-teardown failures were caused by concurrent trace-directory
  cleanup. Both affected desktop tests passed after isolating output directories.
  Thus all 36 executed core scenarios have passing evidence; billing remains paused.
- Final complete built-chunk browser suite: **14 passed**, desktop and 390px.
  The deterministic refresh-token/chunk-recovery regression passed in both sizes.
- Local-media browser suite: four scenarios passed initially; the one interrupted
  by a development-server reload during dependency edits passed when rerun with
  frozen source. This covers all five scenarios, including real speech, large files,
  cached speech, cancellation, denied downloads and no original file transfer.
- Conservative 4-GB/unknown-RAM cases: three passed. These override browser-reported
  RAM and do not certify a physical low-memory device.
- Built `/app` production media test: **passed**, including real document, audio,
  video, image, shipped worker/WASM paths and bounded reviewed cloud requests.
- App ESLint: zero errors and nine existing unused-disable warnings. Landing
  ESLint: passed with no warnings. App/landing TypeScript checks: passed.
- PostgreSQL delta upgrade/downgrade/re-upgrade and RLS assertions: passed.
- Disposable SQLite/app-version rollback rehearsal and metadata drift check: passed.
  Verified old login, new login, old app on expanded schema, old login after
  downgrade and new login after re-upgrade, using synthetic credentials only.
- Landing production build after security updates: passed (Next.js 16.4.6); all
  routes prerendered. React 18 emits a deprecation notice for a future major release;
  this change does not attempt a React major-version migration.
- Container build: local Docker storage reported read-only metadata and could not
  create the disposable PostgreSQL/Redis containers. Do not treat that as passing.

GitHub CI repeats these checks, adds a clean PostgreSQL full-chain migration check
and image builds, and remains a separate remote verification gate until observed.

## Deployment and rollback procedure

1. Require passing release checks and preserve the exact commit/artifacts. Confirm
   hosting restriction cleared. Provision external Redis and all three persistent
   workers, with shared durable storage/database and the same encryption key and
   commit as the API. Production environment metadata currently has no
   `KRUVIM_REDIS_URL` or SMTP settings; a safe rollout depends on configuring these
   and verifying actual worker readiness and mail delivery. Do not enable model
   charges, change the paused paywall or publish legal drafts as part of this release.
   Set `KRUVIM_RELEASE_SHA` to the exact 40-character commit on every worker and
   persistent API, or build the image with `--build-arg RELEASE_SHA=<commit>`.
   Vercel uses `VERCEL_GIT_COMMIT_SHA`. Heartbeat keys include that commit; a
   healthy worker from a different release cannot satisfy readiness.
2. Capture and verify a paired database/object backup. Drain current work and stop
   new admissions during cutover. Preserve failed jobs for explicit review. Apply
   `0019 → 0021` once and verify tables, grants and private-schema access. Confirm
   migration identity with actual queries, not an Alembic stamp.
3. Stage production without assigning domains. Require exact commit in health,
   readiness including all workers, private upload/readback, login/recovery,
   workspace isolation and dry-run completion on the exact staged artifact.
   Promote that artifact and repeat public checks. A preview without matching
   isolated database/storage/workers is not release evidence.
4. Before any rollback, stop new jobs and pause external execution. Preserve the
   current DB snapshot and queue state. Prefer retaining the additive `0021`
   schema while changing application versions. Do **not** downgrade production
   auth tables: dropping token/outbox data loses security and delivery state.
5. The old production app predates auth-version revocation and verified-email
   enforcement. Its login compatibility does not make it a safe rollback after
   password resets or verification changes. Before onboarding new auth traffic,
   test rollback to a build that retains the new authentication guards; afterward
   prefer a forward repair. Never rotate the shared encryption secret merely to
   invalidate tokens: it also protects stored provider credentials.
6. Preserve the original domain/deployment mapping. Test a real staged deployment
   rollback and re-promotion once provider access and workers are operational.
   Until that is observed, the deployment rollback gate remains open even if
   local code and database round-trip rehearsals pass.

This branch provides one reviewed candidate and reproducible checks. Production
must not be declared reconciled until its commit, schema and runtime match this
record and final public smoke checks pass.
