# Forecast Lite (Codex prompt)

Phase 1 of [the cultural weather forecast idea](cultural-weather-forecast.md). Small enough to build solo.
Copy everything inside the block below and give it to Codex.

```text
You are working on Kruvim (FastAPI backend in /backend, React + TypeScript frontend in /frontend, branch `kruvim`).
Add Alembic migrations for schema changes, keep dry-run mode working, follow the existing UI style
(English-only UI), and add tests. Leave LLM API key fields blank by default and keep local-model support
working. Keep this small: reuse the existing data pool, worker cron and LLM provider. No new simulation engine.

Goal: "Kruvim Forecast Lite". Every evening Kruvim publishes 10 public, checkable forecasts about tomorrow in
the UAE. The next evening it scores them automatically against real data it already collects, and shows a
public scoreboard. It must be honest: forecasts can never be edited after publishing, and Kruvim is always
compared with a simple baseline.

1. Forecast types (only types that can be checked automatically from existing connectors)
   - trend_appears: "Topic X will appear in tomorrow's Google Trends daily list for AE"
     (check: RegionalTrendsConnector signals for AE in the next day's window)
   - headline_topic: "Topic X will appear in tomorrow's top UAE news headlines"
     (check: GoogleNewsConnector signals for AE)
   - wiki_top: "Page X will be in tomorrow's top Wikipedia pages (Arabic or English) for the region"
     (check: WikipediaConnector signals)
   - youtube_trending: "A video about X will be in tomorrow's YouTube trending for AE", only if the YouTube
     connector is configured
   Matching uses normalised text plus a fuzzy and embedding similarity threshold (reuse
   datapool/retrieval.py). Store the exact rule and threshold with each forecast so scoring is reproducible.

2. Daily job (arq cron, about 20:00 Asia/Dubai)
   - Gather the last 7 days of AE signals from the data pool, tomorrow's calendar entries, and the current
     cultural moment.
   - One LLM call (role "report") returns exactly 10 forecasts as JSON:
     {type, subject, claim (one plain-English sentence), probability (0.05-0.95), rationale (max 25 words),
     category (sport, entertainment, news, religion and culture, money, tech, other)}.
     Validate it; drop invalid items and retry once.
   - Dry run: generate forecasts with a momentum heuristic (topics rising over the last 3 days), so the whole
     feature works without a model.
   - Baseline: for each forecast, also record the baseline probability from a simple "persistence" rule (did
     it appear in the last 2 days?). This makes "better than a naive guess" measurable.
   - Publish: store each forecast with published_at, target_date and a SHA-256 hash of its content. Published
     forecasts are immutable (no update endpoint; tests enforce this).
   - Safety: never forecast about named private individuals, deaths, crimes by named people, or
     market-moving financial calls. Run the existing datapool/safety.py filter on subjects and claims.

3. Scoring job (arq cron, the next day about 21:00 Asia/Dubai)
   - Resolve each forecast from the target date's signals: hit, miss, or void (source unavailable).
   - Compute the Brier score for Kruvim and for the baseline, the hit rate, and a calibration table
     (probability buckets vs observed frequency). Keep a rolling 7-day and 30-day record.

4. Public page /forecast (no login), mobile-first
   - "Tomorrow in the UAE": the 10 forecast cards, each showing the probability as "72% chance", the claim,
     the short rationale and the category.
   - "Yesterday": each forecast marked hit, miss or void, with the evidence (the matching trend, headline or
     page and its link).
   - Scoreboard: 7- and 30-day hit rate, Brier score vs baseline in plain words ("Kruvim beat the simple
     guess on 5 of the last 7 days"), and a simple calibration chart.
   - An archive page per date, plus a "How this works" section explaining the scoring, the baseline and that
     the results are simulated and automated.
   - A share button per forecast. Generate an Open Graph image card (server-side PNG: Kruvim mark, claim,
     probability, date) so links look good on X, WhatsApp and LinkedIn.
   - A "Get tomorrow's forecast by email" signup that only collects email plus consent into a waitlist
     table. No sending yet, apart from a double-opt-in confirmation via the existing mail path or a console
     backend.

5. Admin
   - Platform admins see job runs, errors and token use, and can re-run a failed generation for a target date
     only before anything is published for that date.
   - A kill switch hides the public page.

6. Tests
   - Forecast JSON validation and safety filtering.
   - Dry-run generation is deterministic.
   - Immutability after publishing (no edits; the hash matches).
   - Scoring with fixtures for hit, miss and void.
   - Brier score and baseline maths.
   - The public API exposes no admin fields.
   - The OG image endpoint returns a PNG.
   - Migrations upgrade from head on SQLite and Postgres.

Rules for delivery:
- One commit per numbered section where practical.
- Keep the existing test suite, ruff, `tsc --noEmit` and the vite build passing.
- Add a short README section on Forecast Lite.
- Finish with a summary of what changed, what was tested and what was not.
```
