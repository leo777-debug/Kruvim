# Shared dataset preparation

Library retrieval loads authorized, query-matching evidence once per environment preparation, ranks once, and reuses evidence selections for agents with identical region/language/audience access filters. There are no extra model calls; this works with every configured provider. The existing environment snapshot freezes the selected evidence for subsequent native/OASIS turns.

Explicit numeric JSON fields and semicolon-separated labelled numeric cells are aggregated in Python once per folder, source file, region and language. Counts, sums, means and ranges describe observed query-matching cells only. Missing values are excluded from field counts; identifiers and free prose are not interpreted as measurements. Summaries are bounded, revision-fingerprinted and included once per selected dataset in each agent context. Existing row IDs, revisions and unverified-evidence labels remain available.

This does not compute population weights or infer percentages/demographic distributions from ambiguous prose. At most four numeric fields are summarized, and a summary exceeding the prompt budget falls back to ordinary retrieved evidence. Existing import/retrieval row limits still apply. There is no global or cross-client cache, and updated entries are reprocessed on the next environment preparation. Regenerate an existing environment to use changed datasets.

Validation: library, visibility and billing suites pass against the production-based release. Dataset tests also cover exact JSON decimal arithmetic, no guessing from prose, file/geography isolation, revision changes, shared cohort reuse, and CSV upload through environment snapshots, simulation completion and report generation in dry-run mode. No paid model requests are used in these checks.
