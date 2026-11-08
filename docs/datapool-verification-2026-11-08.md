# Data pool loading and public upstream feeds — 8 November 2026

The Regions GET endpoint performed upstream collection, per-region snapshot work,
provider resolution and optional model tone estimates during a page read. The live
request took about seven seconds. Several tabs lacked usable loading/error states.
The hosted scheduler refreshed only three feeds, leaving Wikipedia attention
dependent on page-triggered collection. Region checkbox buttons also swallowed
clicks without calling the row's change handler.

Changes:

- Regions uses a bulk latest-snapshot read. It never resolves a model, collects an
  upstream feed, or reserves model credits. Missing and old snapshots are explicit.
- The existing hosted scheduler collects the approved public GDELT, USGS, NASA
  EONET and Wikipedia feeds and publishes hourly context from those saved signals.
  This is a direct-upstream integration, selected by the user; no World Monitor
  hosted API, dashboard scraping, API key or copied application code is used.
- Data pool shows the four upstreams' real status, last check and new-item counts.
- Workspace-scoped queries have a 15-second deadline and a visible manual retry.
  Signals, connectors, datasets, population versions and sources have explicit
  loading, error and empty states. Existing source approval rules remain in force.
- Region checkboxes handle direct/keyboard activation and have accessible names.
- The provider UI exposes the existing Mistral preset. Provider error identity is
  determined from the selected preset/endpoint before the OpenAI-compatible
  transport, so Mistral errors are labelled correctly.

Validation:

- Initial targeted backend run: 14 tests passed (preview, public news and hazards).
- Broader regressions exercised cached source revocation, private tone isolation,
  archived region cutoffs, scheduling, cloud jobs and library flows. Tests for the
  former model-spending GET behavior were updated to the explicit read-only contract.
- Production frontend build, bundle budgets and navigation checks pass.
- Desktop/mobile Data pool tests cover all six tabs and a failed Regions request
  followed by successful retry. A later check also exercises the region checkbox.
- An isolated local workspace fetched real upstream data: GDELT 56 new items,
  NASA EONET 1, Wikipedia 68; USGS succeeded with no matching regional events.
  Twelve regional snapshots were published. No production account was created
  and no subscription or live workspace entitlement was modified for this trial.
- The supplied Mistral key was entered through the password field and stored only
  in the isolated workspace's encrypted provider configuration. Listing returned
  55 models. The connection probe returned HTTP 429, code 1300, “Rate limit
  exceeded”; no successful model-backed simulation is claimed by this check.
- Browser control created a trial named “Mistral browser verification — 8 Nov”
  with 10 voice agents, no crowd/stakeholders, one UAE region and one simulated
  hour. The graph/content request failed on the same provider rate limit. The
  browser displayed the failed-run state; this is not a completed simulation.
- A production snapshot-size check found 2.62 MB across the 12 latest stored
  regional snapshots. The dashboard response now strips internal retrieval
  vectors while the full reproducible vectors remain in the server archive.
- Final checkbox-inclusive Data pool browser run: 4 passed on desktop/mobile.
  Cached source-revocation/retrieval and preview rechecks: 5 passed. Targeted
  Ruff checks passed, including the corrected Mistral provider identity.

No API key is present in this document, source files or committed test fixtures.
