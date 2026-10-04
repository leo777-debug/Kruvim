# Kruvim launch checklist

Everything left between today and a paying beta, grouped by phase. Tick items off as they are done.
Last updated: 2026-10-04.

## Saved for later (do these at the end)
Deliberately postponed. Each one also appears in its own section below.
- [ ] **Payment wall:** plans, checkout, invoices, credit top-ups (see section 6)
- [ ] **Comments feature:** creators' real reel comments into a data pool per creator (see section 5)
- [ ] **AI twins of real, consenting people:** fan panels, the People's Panel, rewards and member revenue share, Twin Charter. The ready-to-send Codex prompt is in [docs/deferred/ai-twins-codex-prompt.md](docs/deferred/ai-twins-codex-prompt.md). Needs legal review first; cash payouts depend on the payment wall.
- [ ] **Manual data imports** for the UAE sources (see section 3)
- [ ] **Licence checks** for Dubai Pulse and every other portal before charging clients (see section 3)

## 1. Verify Codex's latest work (next)
Codex has pushed all three latest prompts. None of it has been tested yet.
- [ ] Fixes: readable report footnotes, Interviews auto-selects an agent, news-tone fallback, flaky test fixed, grouped sidebar
- [ ] Long-term agent memory: memories carry across runs, returning panel, "Fresh audience" toggle, reset, accuracy comparison
- [ ] UAE source registry, emirate-level population (raking, conflicts, placeholders) and emirate data pool
- [ ] Full test suite, lint, type-check and build pass
- [ ] Recorded click-through of the whole flow, plus every page not yet tested by hand: Audiences (save/load), My audience (save breakdown), Monitoring (add a feed), Population, Settings, Usage, Platform admin

## 2. Real-model testing
- [ ] Pick the model(s): Mistral Small / Gemini Flash-Lite for agents, a stronger model for the report
- [ ] One real run with a cheap model; record actual tokens and cost per test
- [ ] Judge quality of real agent reactions, report and interviews (not just dry-run)
- [ ] Route models per role (agents cheap, report stronger) to cut cost
- [ ] Test a local model (Ollama or LM Studio) end to end
- [ ] Set the free-trial size from the measured cost (e.g. 1,000 credits or 40 voice agents per test)

## 3. Data (UAE)
- [ ] **Manual data imports:** download official files (FCSC / bayanat.ae, SCAD, Dubai Statistics Center / Dubai Pulse, Sharjah statistics, KHDA, ADEK, Dubai Land Department, RTA, Dubai Economy and Tourism, Central Bank, DoH / DHA / MOHAP, TDRA, GLMM, UN migrant stock) and upload them via the import screen, following Codex's pending-import checklist
- [ ] **Licence checks:** confirm commercial-use terms for Dubai Pulse and every other portal before charging clients; keep unclear sources out of production until approved
- [ ] Rebuild and activate the UAE population once real sources replace placeholders
- [ ] Data-source keys: YouTube API key, Reddit app, Bluesky account (X paid tier optional)

## 4. Production stack and deployment
- [ ] Run the Docker / Postgres / Redis / worker stack locally (fix Docker Desktop first)
- [ ] Choose hosting in or near the Gulf (AWS Bahrain/UAE or Google Cloud Dammam) for data residency
- [ ] Managed Postgres with pgvector, Redis, S3-compatible bucket, background workers
- [ ] Domain, DNS, HTTPS
- [ ] Email delivery for invites and password resets (verify it exists; add a provider if not)
- [ ] Automatic daily backups for the database and the bucket; test a restore
- [ ] Error tracking and uptime monitoring (e.g. Sentry plus a status check)
- [ ] CI/CD: tests on every push, deploy from the main branch
- [ ] Load test: many users at once, several simulations running, 1M-person population in memory
- [ ] Security review: login, workspace isolation, uploads, share links, API keys, rate limits
- [ ] Merge PR leo777-debug/Kruvim#2 (`kruvim` into `master`)

## 5. Creator and platform connections
- [ ] Apply for developer apps: TikTok, Meta (Instagram), Google (YouTube Analytics) so "My audience" can connect real accounts
- [ ] **Comments feature (deferred from v1):** creators' real reel comments into a data pool per creator

## 6. Money
- [ ] **Payment wall:** plans, checkout, invoices, credit top-ups (the credit ledger already accepts purchases). Check Stripe / Checkout.com / Tap / Telr for the UAE
- [ ] Final pricing: creators, business seats, per-study for agencies, enterprise annual
- [ ] Usage alerts so LLM spend can't run away

## 7. Legal and company
- [ ] UAE company or free-zone licence (e.g. via Hub71 or in5)
- [ ] Terms of service, privacy policy, cookie consent (UAE data protection law, DIFC/ADGM, Saudi PDPL for KSA clients)
- [ ] Acceptable-use policy: no election manipulation, no targeting individuals, results labelled as simulated
- [ ] Data processing agreement template for business clients
- [ ] Trademark "Kruvim"

## 8. Business product (to compete with Aaru)
- [ ] Research module: questionnaires, MaxDiff, pricing, conjoint, cross-tabs, PowerPoint export
- [ ] Ad pretesting with standard measures (recall, persuasion, emotion trace)
- [ ] Crisis / PR war room
- [ ] Always-on brand tracker
- [ ] Customer twins from client segments
- [ ] Enterprise: SSO, in-country hosting, private deployment option

## 9. Go-to-market
- [ ] Twin study with a research partner (YouGov MENA / Ipsos / local), published
- [ ] Data partnerships list and outreach (e&, du, Majid Al Futtaim, Network International, panel firms)
- [ ] Website / landing page, demo video, pitch deck
- [ ] Ramadan 2027 campaign push to agencies (Ramadan starts around early February 2027)
- [ ] Weekly "Kruvim Pulse" simulated poll for LinkedIn / X
- [ ] Private beta with 10-20 creators and 2-3 agencies, then the 100-user trial
