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
  app/models/         SQLAlchemy models (28 tables)
  app/services/       llm, population, datapool, knowledge, simulation, report, interaction, quotas
  app/workers/        arq worker and tasks
  migrations/         Alembic
  tests/              pytest
  tools/              mock OpenAI-compatible server
frontend/
  src/components/     UI primitives, layout, live graph, charts
  src/features/       pages: dashboard, projects, simulations (five steps), data pool, population, settings, admin
docker-compose.yml    postgres, redis, api, worker, web, optional ollama
```

## Limits worth knowing

* Agent reactions are model outputs grounded in demographics and live context, not measurements of real people.
  Use *Calibration* to record real results; Kruvim reports how well predictions rank actual outcomes.
* The population is synthetic and built from regional priors until it is calibrated with survey data.
* Some free sources rate-limit aggressively (GDELT in particular); connectors report their status on the data pool page.
