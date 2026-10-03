# Kruvim

Kruvim tests a piece of content against a synthetic audience before it is published. It builds a knowledge graph
around the content, places it in front of a population of one million demographically grounded agents conditioned on
what is happening in each region right now (weather, news, news tone, holidays, economy, social trends), runs a
two-platform social simulation, and has an analyst agent write a report you can interrogate.

```
Content + question ──► 1 Knowledge graph ──► 2 Environment ──► 3 Simulation ──► 4 Report ──► 5 Interviews
                         ontology, entities     voice agents      feed + forum      ReAct analyst   any agent,
                         live regional context  stakeholders      local clocks      with tools      surveys
                                                crowd, config     live events
```

## How it works

**Population.** One million agents are rows in NumPy arrays, not running models: age, sex, region, origin, language,
education, income, OCEAN personality, attitudes, platform use, interests and a heavy-tailed, homophilous follow graph.
Regional priors are built in and can be calibrated from survey microdata (Arab Barometer, Pew, WVS, census) under
*Data pool → Survey data*.

**Hybrid swarm.** Calling a language model a million times per test is neither affordable nor necessary.

| Tier | Count (configurable) | How it behaves |
| --- | --- | --- |
| Voice agents | 40–2,000 | Stratified sample of the audience. A language model reacts in character, then acts on the feed and forum each round. |
| Stakeholder accounts | 0–15 | Brands, media and public figures from the knowledge graph, played by the model. |
| Crowd agents | up to 250,000 | Vectorised statistical policy: see, like, repost, upvote, drift toward their feed. |
| Population | 1,000,000 | A ridge "reaction surface" fitted on the voice agents projects a reaction onto every agent, with bootstrap confidence intervals; an independent-cascade model on the follow graph estimates reach. |

**Live data pool.** Keyless connectors run on a schedule (Open-Meteo, Google News, GDELT tone, Wikipedia attention,
public holidays, exchange rates, Mastodon and Bluesky trends); Reddit, YouTube, X and Bluesky search work when keys are
added. Every hour each region's state is archived, so a simulation can be backtested at any past moment and agents see
the news people actually saw.

**The five steps** mirror the MiroFish workflow and stream every change to the browser over server-sent events:
graph deltas, agent reactions, posts and actions, round metrics and the analyst's tool calls. During a run you can
pause, resume, change pacing, stop early or inject a breaking-news event.

## Architecture

```
            ┌────────────┐   /api (REST + SSE)   ┌──────────────┐   jobs (arq)   ┌──────────────┐
 Browser ──►│ web: nginx │──────────────────────►│ api: FastAPI │──────────────►│ worker(s)    │
            │ React SPA  │                       │ gunicorn     │◄── events ────│ simulations, │
            └────────────┘                       └──────┬───────┘   (Redis      │ graph, report│
                                                        │           pub/sub)    └──────┬───────┘
                                              ┌─────────┴─────────┐                    │
                                              │ PostgreSQL  Redis │◄───────────────────┘
                                              └───────────────────┘   shared volume / S3: uploads, population
```

* **Backend** `backend/`: FastAPI, SQLAlchemy 2 (async), Alembic, arq workers, NumPy. Model providers: any
  OpenAI-compatible API (DeepSeek, OpenRouter, OpenAI, Groq, Together, custom), the Anthropic SDK, and local servers
  (Ollama, LM Studio, llama.cpp, vLLM). Dry-run mode needs no model at all.
* **Frontend** `frontend/`: React 18, TypeScript, Vite, Tailwind, Radix UI, TanStack Query, react-force-graph, Recharts.
* **Multi-tenancy**: organisations, memberships with roles (owner, admin, member, viewer), invites, API keys
  (`krv_…`, hashed, role-scoped), per-organisation encrypted provider and connector credentials, plans, credit
  ledger, usage metering and an audit log.
* **Operations**: JSON logs with request ids, Prometheus metrics at `/metrics`, `/healthz` and `/readyz`, Redis-backed
  rate limiting, security headers, rotating refresh tokens with reuse detection.

## Quick start (local development)

Requirements: Python 3.11–3.13 (3.14 works without the `asyncpg` driver), Node 20+. Redis and PostgreSQL are optional
locally: without `KRUVIM_REDIS_URL` jobs run in-process, and SQLite is the default database.

```bash
cd backend
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
python -m scripts.seed_demo                          # optional: local demo account, see scripts/seed_demo.py
uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend
npm install
npm run dev                                          # http://localhost:5173, proxies /api to :8000
```

The first account registered becomes the platform administrator. With no model connected everything runs in dry-run
mode; add a key or a local model under *Settings → Model provider*. The first simulation builds the 1M-agent
population (about 15 seconds) and caches it on disk.

To exercise the real provider path without spending credits, run `python tools/mock_openai_server.py` and choose
*Other OpenAI-compatible* with base URL `http://127.0.0.1:8499/v1` and key `test-key`.

## Production (Docker Compose)

```bash
cp .env.example .env            # set KRUVIM_SECRET_KEY, POSTGRES_PASSWORD, KRUVIM_PUBLIC_URL, KRUVIM_CORS_ORIGINS
docker compose up -d --build    # http://localhost:8080
docker compose up -d --scale worker=4
docker compose --profile local-llm up -d   # optional Ollama container
```

The API container runs `alembic upgrade head` before starting. Put TLS in front of the `web` service (a load balancer
or any reverse proxy); nginx already passes server-sent events through unbuffered.

### Scaling

* **API** is stateless: run more replicas behind the load balancer and raise `WEB_CONCURRENCY`.
* **Workers** run graph builds, simulations, reports and surveys. Throughput scales with worker replicas and
  `KRUVIM_WORKER_MAX_JOBS`; per-organisation concurrency is capped by plan.
* **Model throughput** is bounded by the provider. Each organisation's provider config has its own concurrency limit.
* **Events** are persisted in `sim_events` and fanned out over Redis pub/sub, so any API replica can stream any run
  and clients resume from `Last-Event-ID` after a reconnect.
* **Population** files live on the shared volume (or S3); each process loads the active version once.

## Configuration

All settings are environment variables prefixed with `KRUVIM_` (see `.env.example` and `backend/app/core/config.py`).

| Variable | Purpose |
| --- | --- |
| `KRUVIM_SECRET_KEY` | Signs tokens and derives the encryption key for stored credentials. Required in production. |
| `KRUVIM_DATABASE_URL` | `postgresql+asyncpg://…` in production; SQLite by default. |
| `KRUVIM_REDIS_URL` | Enables the arq job queue, event fan-out and shared rate limits. |
| `KRUVIM_LLM_*` | Optional platform-wide model key. Organisations without their own key use it and are metered in credits. Left blank, everything runs in dry-run. |
| `KRUVIM_REDDIT_*`, `KRUVIM_YOUTUBE_API_KEY`, `KRUVIM_X_BEARER_TOKEN`, `KRUVIM_BLUESKY_*` | Optional social connectors. |
| `KRUVIM_POPULATION_SIZE` | Population size (default 1,000,000). |
| `KRUVIM_STORAGE_BACKEND`, `KRUVIM_S3_*` | Local volume or S3-compatible object storage for uploads. |

## Creator analytics and audience twins

Under **My audience**, connect a creator-owned YouTube, TikTok or Instagram account using read-only OAuth.
Register provider applications, set the `KRUVIM_*_CLIENT_ID` / `CLIENT_SECRET` values, and register the exact callback
`<KRUVIM_PUBLIC_URL>/api/v1/social/<platform>/callback`. Provider review/approved scopes are required for production;
Instagram needs a professional account. These credentials are distinct from the public-data YouTube API key.

Complete a test, then link the published post ID for variant A and, optionally, B in its Overview. Ownership is checked
before linking. The development scheduler and arq cron sync aggregate outcomes, refresh tokens and update Calibration
without manual metric entry. Credentials are encrypted, OAuth state expires after ten minutes and is consumed once,
and all private analytics queries are workspace-scoped. A database lease prevents overlapping syncs; each pass processes
up to five pending posts per account, oldest observation first. Snapshots finalize at the first sync after seven days.
Disconnect removes credentials and post mappings; existing calibration reports remain. Removing a post link removes
its automatic calibration report. No comment text or individual follower records are collected.

| Provider | Outcomes | Audience breakdown |
| --- | --- | --- |
| YouTube | Views, likes, shares, comment count, average view percentage | Subscribed-viewer country, age and gender; this describes active viewers, not the complete follower base |
| TikTok Display API | Views, likes, shares and comment count | Not exposed by this API; use the manual breakdown |
| Instagram | Available media views and engagement counts | Follower country, age and gender, subject to professional-account eligibility and privacy thresholds |

Unavailable/private metrics remain null, never fabricated zeros. YouTube replays can push average view percentage above
100%; the calibration retention field is capped at 100%. Instagram retention is not exposed by this connector. TikTok
retention and follower demographics require additional eligible Business analytics access, which is not implemented.

Use **Match my audience** when creating a simulation, or pass `audience.follower_split` with percentage maps named
`countries`, `ages`, and `genders`. Supplied marginals must total 100%. Sampling and population summaries are weighted
to those marginals; other traits remain synthetic priors. Results disclose unsupported country/gender shares, clipped
age bands (the population covers 16–70), and residual fitting error. Connected breakdowns refresh automatically; each
prepared simulation keeps its own copy so later syncs do not change an existing run. Six built-in creator presets are
available. Workspace memory keeps the latest 20 simulated observations and can be reset.

Short-video results expose rewatch, stitch/duet, sound-reuse and comment-bait reactions; formula defaults support dry-run.
Rewatch and duet likelihood adjust crowd sharing and cascade amplification. Prepared snapshots store deterministic local
hash embeddings and per-agent retrieved signal evidence. Set `KRUVIM_EMBEDDING_MODEL` to use the configured compatible
provider's embedding endpoint: one batch includes all candidate signals and agent queries; unsupported models or
dimensions fall back locally. Vectors are stored in PostgreSQL pgvector (128 dimensions with a cosine HNSW index), or
JSON/NumPy on SQLite. `KRUVIM_EMBEDDING_PRICE_PER_MILLION` lets the usage panel report the extra cost; unknown prices are
not treated as zero. Historical runs without an archive disclose missing context instead of using today's data.

### Accuracy and shared calibration

The unauthenticated page `/accuracy` and API `/api/v1/public/accuracy` publish actual ranking accuracy with a Wilson 95%
confidence interval. Predictions are frozen when posts are linked. Eligible pairs must use the same completed run,
predate both publications, contain actual views observed 7–8 days after publication, and have a decisive model winner.
Dry runs, competitor comparisons, ties, late snapshots and missing outcomes are excluded. These are observational creator
comparisons, not randomized experiments. No example accuracy percentage or invented test count is published.

Public reporting and shared source weights require explicit per-account opt-in, at least `KRUVIM_ACCURACY_MIN_TESTS`
eligible pairs across `KRUVIM_ACCURACY_MIN_WORKSPACES` workspaces. Until then, the public report makes no accuracy claim.
Source weights associate each included source with A/B correctness per niche; they use equal weights until sufficient
evidence, and do not claim causation. Shared learning currently adjusts retrieval source weights; it does not retrain
an LLM or replace global demographic priors with creators' private follower data.

### Pipeline operation

Graph preparation triggers bounded topic pulls across Google News, Wikipedia and searchable social connectors. Results
are private to the workspace and tagged with the simulation. Completed sources are retained within a 20-second budget.
No external fetch occurs inside the reaction engine. Hourly snapshots include per-source freshness; limits are configured
through `KRUVIM_SIGNAL_MAX_AGE_HOURS`. A daily regional cultural synthesis uses the platform report model, once per region
per UTC day outside simulation billing, with a deterministic template when no model is configured or the call fails.

In production, start the `connector-worker` service as well as simulation workers. The dedicated `kruvim:connectors` queue
uses `KRUVIM_CONNECTOR_CONCURRENCY`, distributed per-source exclusion, and configurable minimum request spacing through
`KRUVIM_CONNECTOR_MIN_INTERVAL_SECONDS`. Old snapshots are gzip-compressed to S3-compatible storage when configured,
after `KRUVIM_SNAPSHOT_ARCHIVE_DAYS` (default 30), and restored for backtests. Database contents are cleared only after a
successful object upload. Trend lifecycle labels use at least three dated, numeric observations from the same source;
insufficient history is explicitly labelled unknown. Matches without comparable measurements establish relevance only.

The Compose PostgreSQL image includes pgvector. Existing PostgreSQL installations need the vector extension available
to the migration role. End-to-end production PostgreSQL/Redis/S3 operation and real OAuth accounts require their running
services and credentials; local tests use SQLite, dry-run models and mocked provider responses.

## Billing status

Plans (Free, Pro, Business, Enterprise), monthly credit grants, the credit ledger and usage metering are implemented.
One credit is one model call on the platform key; organisations using their own key or a local model are not metered.
**Purchasing credits and plan checkout are not implemented yet.** The ledger already accepts `purchase` entries, so a
payment provider (for example Stripe Checkout plus a webhook that writes ledger entries and changes the plan) plugs in
without schema changes. Until then a platform administrator changes plans and grants credits under *Platform admin*.

## API

Everything in the UI is available over the REST API at `/api/v1`, documented at `/api/docs`. Authenticate with a
session token or an API key created under *Settings → API keys*:

```bash
curl -H "Authorization: Bearer krv_..." https://kruvim.example.com/api/v1/projects
```

Live runs stream from `GET /api/v1/simulations/{id}/events` as server-sent events.

## Tests

```bash
cd backend && pytest            # unit tests, the full workflow in dry-run, and the full workflow through a mock model server
ruff check app tests scripts migrations tools
cd frontend && npx tsc --noEmit && npx vite build
```

## Repository layout

```
backend/
  app/api/            routes, dependencies (auth, roles, tenancy)
  app/core/           config, security, logging, metrics, rate limiting
  app/models/         SQLAlchemy models
  app/services/       llm, population, datapool, knowledge, simulation, report, interaction, quotas
  app/workers/        arq worker and tasks
  migrations/         Alembic
  tests/              pytest
  tools/              mock OpenAI-compatible server
frontend/
  src/components/     UI primitives, layout, live graph, charts
  src/features/       pages: dashboard, projects, simulations (five steps), data pool, population, settings, admin
docker-compose.yml    postgres, redis, api, worker, connector-worker, web, optional ollama
```

## Limits worth knowing

* Agent reactions are model outputs grounded in demographics and live context, not measurements of real people.
  Link published posts to sync real results automatically; Calibration also accepts manual results.
* The population is synthetic and built from regional priors until it is calibrated with survey data.
* Some free sources rate-limit aggressively (GDELT in particular); connectors report their status on the data pool page.

## October click-through fixes (Part A)

Demo SQLite installs now run Alembic before seeding; legacy databases containing every model table are stamped at head. Reports notify clients after committing, and completed runs keep polling until their report finishes.

Regional trend RSS is fetched per country. Global social items are admitted only when they explicitly reference the requested region. Wikipedia discovery checks titles and categories before ingestion; cached snapshots and retrieval apply the title filter too. Saudi dates use the built-in holiday calendar when a remote source is unavailable, and unavailable news tone is labeled clearly. These sources remain external and may rate-limit or return no matching trends.

The UI has shared platform names, separate creator-preset labels, real plan feed limits, a shared region picker, and an Accuracy sidebar entry. Retrieval accounting is in Method. Audience connections stack as cards below 640px. Voice selection preserves weighted demographic proportions and mixes the interview list. LLM keys remain blank by default; dry-run and OpenAI-compatible local providers remain supported.

Validation: 32 backend tests passed; Ruff, TypeScript and the production Vite build passed. All 17 formats completed in an isolated dry-run workspace; 40 concurrent reads returned HTTP 200. Browser checks at 390px covered the 12 main pages, a project, the new-run form and completed results. Run `frontend/tools/verify-mobile.ps1 -Browser <agent-browser executable> -ProjectId <id> -RunId <id>` against an authenticated browser session named `kruvim-gaps`. Country RSS and Wikipedia category responses were tested with fixtures; live upstream availability and paid-model output were not certified.

### Part B · Learning graph and fact history
After each debate round, one extraction batch turns agent posts/comments into attributed entities, claims and support/opposition edges. Claims are unverified and retain source post ids; invalid ids/authors are rejected. Dry-run uses a deterministic extractor. New relationships stream after persistence.

Migration `0004` adds validity rounds and timestamps to edges, backfilling existing rows. Stance changes and contradictions close relationships rather than deleting them. `GET /simulations/{id}/graph` returns the current view; `?history=true` returns full history and `?round=N` returns the view at a round. The graph panel's superseded-facts toggle displays closed edges as muted dashed lines. Tests cover batching, provenance, intervals, historical queries, contradictions and cross-workspace denial.

### Part B · Analyst search and citations
`graph_search` and `quick_search` combine keywords with native 128-dimensional embeddings. PostgreSQL uses pgvector/HNSW candidates; SQLite ranks bounded local candidates. These are feature-hashing embeddings, not a claim of paid semantic-model quality. Migration `0005` embeds legacy graph nodes. `insight_search` splits questions into 3–5 sub-questions (one model call, or deterministic dry-run), searches each, and expands one or two graph hops. `panorama_search` includes superseded facts and validity dates. Tools return node/edge ids. Reports cite persisted graph observations; invented references are rejected and each section retains an evidence list. Tests cover expansion, history, question batching, tenant scoping and report references. PostgreSQL execution is not yet verified locally.

### Part B · Agent discovery and comment votes
Feed and forum agents can SEARCH_POSTS, SEARCH_USER, VIEW_TRENDS, REFRESH, MUTE, LIKE_COMMENT and DISLIKE_COMMENT. Searches combine keywords/native embeddings over the run's own posts/accounts. Results are retained in agent memory; foreign-platform and unseen targets are rejected. Muting hides accounts from that agent's recommendations and searches. Each agent has one reversible vote per comment; votes affect ranking. Dry-run policies exercise discovery and comment votes, and crowd comment engagement gets explicit action labels. Results include action counters; the live activity log and action transcript filter by action/platform. Tests cover discovery results, mute exclusion, invalid targets, deduplicated/reversed votes and dry-run policies.
