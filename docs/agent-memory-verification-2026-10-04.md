# Native agent memory verification

Nine implementation commits cover the requested data model, writing, recall, returning panel, crowd/projection,
maintenance, controls, calibration comparison, and regression/documentation work. Migration 0007 extends 0006 with
workspace-owned person memories and numeric creator affinity. No external memory dependency or provider-key default
was added; the interface remains English-only.

## Automated checks

- Final full backend suite: **69 passed**. The preceding randomized full suite (seed 104) passed 68 tests before the
  additional same-run relationship-change test was added. An earlier normal suite passed 67 tests. These are three
  consecutive successful full-suite executions as coverage grew, not a 20-run stability campaign for this feature.
- Twelve memory tests cover SQLite migration upgrade/downgrade, PostgreSQL DDL/vector-index contracts, batched writing,
  privacy of writer inputs, idempotence, deterministic dry output, tenant isolation, relevance/recency/importance and
  estimated token budgets, frozen A/B recall, returning segment quotas and shortages, Fresh history exclusion,
  interview recall, affinity/projection features, consolidation and repeated decay, retention and physical caps,
  confirmed admin-only audited resets, canonical creator-only resets, and latest follow/mute relationship state.
- The integrated lifecycle completes three dry A/B runs through the application jobs: a first exposure, a returning
  panel using only earlier memory IDs, and a Fresh run with empty text and numeric history. Stakeholder memory is
  written under a stable canonical key. Real-outcome comparison fixtures test minimum cohorts, format/platform
  separation, eligibility and A/B deduplication.
- Ruff over application, migrations, tests and tools passed. TypeScript `tsc -b --noEmit`, navigation regression,
  agent-selection regression and the production Vite build passed.
- The OpenAI-compatible local protocol fixture now understands the batched memory-writer response. Existing provider
  and local-model routing tests remain part of the passing full suite.

## Browser checks

The production frontend used an offline disposable SQLite server with three completed A/B runs, 20 voice agents and
one fictional stakeholder per run, and a 40,000-person verification population. Interviews and the agent sheet showed
simulated memories, newest first, source-run links, importance and creator affinity. The returning Method section
reported 20 returning agents and 74 recalled memories; the Fresh Method section reported zero returning agents and
zero recalled memories, with history ignored. Calibration displayed the insufficient-outcomes state and its
observational-comparison limitations.

New simulation defaulted to 0% for an unseen creator and 60% after selecting a creator with history. Fresh audience
disabled the returning-percentage field. My audience displayed counts and affinity, creator selection and a reset
confirmation dialog; confirming reset cleared the disposable workspace's count from 41 agents to zero. Desktop and
390px checks found no horizontal page/main overflow on the new form, My audience,
Interviews, results and Calibration. No browser console errors were recorded. Fixture data lives only in the
disposable verifier database, never the normal workspace database.

## Verification limits

An actual PostgreSQL/pgvector migration and query execution could not be run because the installed Docker Desktop
engine was unavailable. SQLite migration execution and PostgreSQL DDL compilation passed. The opt-in
`python -m tools.verify_memory_postgres` tool creates a randomly named scratch database, upgrades 0006 → head and
checks the HNSW index and tenant-isolated vector recall, then drops only that scratch database.

Redis/arq deployment execution, paid-model memory quality, an installed Ollama/GPU model, production-scale performance
and a measured accuracy improvement on real creator outcomes were not verified. Calibration requires comparable
linked live outcomes before reporting a result; fixtures cannot establish that memory actually improves accuracy.
Nightly scheduling registration and consolidation behavior were checked through code and injected-clock tests.
