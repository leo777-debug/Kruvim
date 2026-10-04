# Deferred: AI twins of real, consenting people (Codex prompt)

Saved for later on 2026-10-04. Not started. Copy everything inside the block below and give it to Codex when
you are ready to build this feature. Before real people join, get legal review of the consent text, the Twin
Charter and the member revenue share (UAE data protection law). Cash payouts depend on the payment wall.

```text
You are working on Kruvim (FastAPI backend in /backend, React + TypeScript frontend in /frontend, branch `kruvim`).
Keep everything multi-tenant where it applies (scope by org_id), add Alembic migrations for schema changes, keep
dry-run mode working, follow the existing UI style (English-only UI), and add tests for each part. Leave LLM API
key fields blank by default and keep local-model support working.

Goal: AI twins of real, consenting people.
Today every voice agent is synthetic. Add real people ("participants") who join by choice, give a short AI
interview and get a digital twin that answers simulations for them. Twins come from two sources:
  a) Fan panels: a creator shares an invite link and their followers join that creator's private panel.
  b) The People's Panel: anyone can join a shared pool that every customer can test against (e.g. a
     journalist with no followers targets "Filipino nurses in Abu Dhabi, 25-40").
Participants earn rewards when their twin is used, control what it is used for, and can delete it at any time.
Synthetic agents remain for scale; twins become the trusted core.

1. Participants (separate from workspace users)
   - New participant accounts: email plus phone or email verification, 18+ age confirmation, country,
     emirate/city, nationality group, age band, gender, languages, and optional occupation and income band.
     Reuse the population dimensions from population/features.py so twins map onto audience filters.
   - A mobile-first participant area (/me routes on the same frontend, separate login) with:
     - their twin's profile summary
     - studies their twin took part in (category and date only, never confidential client content)
     - rewards balance and history
     - pending "check" questions
     - controls: blocked topics (politics, gambling, alcohol, religion, finance, health and others,
       configurable), pause twin, export my data, delete twin and account permanently (hard delete of the
       transcript, profile and embeddings; keep only anonymised, aggregate study results)
   - Consent: versioned consent text and a versioned Twin Charter (public page /charter). Store each
     acceptance (participant, version, timestamp). A material change to the Charter requires re-acceptance
     before the twin is used again.

2. The AI interview (building the twin)
   - A ~20-minute guided interview by an interviewer agent: life and routine, values, media and platforms,
     content tastes (what makes them watch, share, scroll), shopping and money habits, community and
     language, opinions on common topics. Follow-up questions adapt to the answers.
   - Text chat first. Voice is optional: browser recording sent to a speech-to-text provider configured in
     Settings, local or remote; the interview works without voice. The UI stays English, but participants may
     answer in any language the configured model handles. Store the language used.
   - Quality and fraud checks:
     - minimum length and attention checks
     - duplicate detection (same device or contact, near-identical answers)
     - rate limits
     - an admin review queue for suspicious sign-ups
   - Output:
     - a structured twin profile (traits, tastes, platform habits, stances, speaking style)
     - a private memory summary
     - embeddings for matching
     - the transcript, encrypted at rest and visible only to the participant and platform admins with an
       audit-log entry
   - Participants can redo or extend the interview at any time; the twin is versioned.
   - Dry run uses a scripted interview and a rule-based profile builder.

3. Fan panels (creators)
   - In My audience, add "My fan panel":
     - create an invite link (and QR code) with an optional welcome note
     - see panel size, an aggregate breakdown (emirate, age band, gender, nationality group, only for groups
       of at least 10), average twin accuracy, and invite conversions
   - A fan who joins through a link is in that creator's private panel. They can also opt in to the People's
     Panel (a separate, explicit checkbox, default off).
   - A creator never sees fans' identities or contact details, only aggregates.

4. The People's Panel (shared pool)
   - Participants who opted in are available to every workspace.
   - In the new-simulation audience builder, add an "Audience source" choice:
     - Synthetic (today's behaviour)
     - My fan panel
     - People's Panel
     - Mixed: twins first, topped up with synthetic agents
   - Show live coverage before running, e.g. "142 matching twins; 58 synthetic agents will be added".
   - Match twins to the requested audience with the existing stratified sampler, respecting each twin's
     blocked topics and pause state, and spreading usage fairly (cap studies per twin per week, configurable).

5. Twins inside simulations
   - Twin-backed voice agents use the twin profile and memory instead of a generated persona. Every agent
     carries a source label (twin or synthetic). Results, the Method tab and reports show how many voices
     were real-person twins.
   - Interviews (step 5) with a twin are allowed, but:
     - the agent sheet says "AI twin of a real participant, not the person"
     - a pseudonym is shown, never the real name
     - the twin must refuse to reveal identifying details (name, employer, exact address, contacts) and
       must never claim to be the actual person
     - add tests for these refusals
   - Segment results built from twins are suppressed below a minimum group size of 10 (k-anonymity) and
     merged into a larger group instead.
   - Twins are never used for content in a blocked topic.
   - Add a server-side topic classifier for the content card; dry run uses keyword rules.

6. Checks and accuracy
   - After a study, send a small random sample (default 2% of participating twins, at least 3 people) a short
     "check" in their participant area and by email: "Your twin said this about a video. Is that what you'd
     think?" Options: agree / partly / no, plus an optional note.
   - Store the result, update that twin's accuracy score (rolling, recency-weighted), and use corrections as
     new memory/profile hints for the next twin version.
   - Each study shows a measured "twin match rate" once enough checks return, with sample size and an
     interval. Before then it shows "pending".
   - Twins with a low accuracy score get lower weight and are asked to refresh their interview.

7. Rewards ledger and member revenue share (no cash payouts yet)
   - A participant rewards ledger in points:
     - points per study the twin is used in, plus a bonus for answered checks
     - a monthly allocation from a members' revenue-share pool: a configurable % of study revenue (default
       20%), split by usage multiplied by accuracy
     - all values configurable by platform admins
   - Real money is not paid yet (the payment wall is not built). Add a payout-request stub and an admin export
     (CSV) of balances, so payouts can be added later with a provider. Label it "Rewards are recorded now and
     paid out once payouts launch".
   - Platform admin view: pool size, allocation run history, top-level statistics. Never show individual
     identities next to client studies.

8. Twin Charter
   - The /charter public page renders the current Charter version. The initial text is a short plain-English
     draft covering:
     - consent and deletion
     - no political persuasion targeting individuals or groups
     - no impersonation or voice cloning
     - no use outside Kruvim
     - topic opt-outs
     - minimum group sizes
     - the member revenue share
   - Mark it clearly "Draft - pending legal review".
   - Member voting on Charter changes is out of scope now. Add a placeholder section "Member votes (coming
     soon)".

9. Privacy, security and operations
   - Participant data is global, not owned by any workspace. Workspaces only ever receive twin-agent
     behaviour and aggregates.
   - Encrypt transcripts and contact details at rest (reuse core/crypto.py).
   - Audit-log admin access.
   - Data export (JSON) and hard delete work end to end.
   - Email notifications use the existing mail path; if none exists, add a provider interface with a console
     backend for development.

10. Tests
   - Signup, verification and consent records.
   - The interview builds a profile; dry run is deterministic.
   - A fan joining via an invite lands in the right panel; the People's Panel requires the opt-in.
   - Matching respects blocked topics, pause and the weekly cap.
   - Mixed audiences top up with synthetic agents and label sources.
   - k-anonymity suppression works.
   - Twin refusals of identifying details.
   - Checks update accuracy, and the study match rate appears only above the minimum sample.
   - Ledger allocations add up to the pool.
   - Hard delete removes the transcript, profile and embeddings.
   - No identities leak into workspace APIs.
   - Migrations upgrade from head on SQLite and Postgres.

Rules for delivery:
- One commit per numbered section where practical.
- Keep the existing test suite, ruff, `tsc --noEmit` and the vite build passing.
- Update the README with the twin architecture, the privacy model and how to run a pilot.
- Finish with a summary of what changed, what was tested and what was not, and anything you could not complete
  and why.
```
