# Import your own creator analytics

Open **My audience → Import analytics**. Choose TikTok, Instagram or YouTube and
either post performance or a follower breakdown. Upload a CSV or XLSX containing
your **own aggregate data**, confirm that it contains no follower identities, and
preview the file. Individual follower names, handles, contacts and comments are
not accepted. Remove those columns before uploading. The importer rejects known
identity headers, email addresses, formula cells and oversized workbooks.

Select the columns explicitly, preview the mapped rows, then import. You can name
and save a mapping for later exports from the same platform. Files have a 25 MB
limit and up to 10,000 rows; the first worksheet of an XLSX is used. Upload another
file for another worksheet or snapshot. Only CSV/XLSX are accepted, not account
archive ZIPs. A simple manual-post form is available without an export.

**Confirmed real export formats: none.** No real creator export samples were
available during implementation. All three platforms therefore use the generic
mapper. The repository fixtures contain synthetic test values and are explicitly
not evidence of a platform's export layout. We ship no guessed platform preset.

## Mapping and native units

Post data requires a date and at least one observed metric. Map title/caption,
format, views, likes, comments, shares, saves, reach, average watch time, completion
or average percentage watched where available. Watch time accepts seconds or
`mm:ss`/`hh:mm:ss`; completion and percentage watched require explicit percent
versus fraction units. Counts must be whole, nonnegative numbers. Missing cells
stay missing and are excluded from a metric's median, rather than becoming zero.
Select a date format and time zone for dates without an offset. Posting-time
patterns are displayed in UTC. Supply the observation window, such as first seven
days or lifetime: different windows are not automatically comparable.

Optional length and hook-style columns support descriptive best-post patterns;
Kruvim does not invent them from missing exports. The best quartile is chosen from
posts with actual view counts. Format, length, hook and posting time are observed
associations, not causal findings.

Follower files use category/value columns and either a fixed breakdown or a
dimension column: `countries`, `cities`, `ages`, `genders`, `active_hours`. Optional
category mappings translate export labels into country codes, supported age bands
and genders. Each complete percentage marginal must sum to approximately 100;
counts need an explicit complete-distribution confirmation. Incomplete/top-country
tables are kept for display and excluded from matching, with coverage gaps shown.
Each file must describe one snapshot without duplicate categories.

Valid country, city/emirate, age and gender marginals fill **My audience** directly.
Choose **Match my audience** in a new test. The sampler rakes the available
synthetic people to these marginals; other traits remain synthetic and unsupported
cities are disclosed. Activity-hour bins are retained and displayed; they do not
replace the synthetic hourly activity policy.

## Baselines and calibration

The imported posts create private per-platform medians with metric sample sizes.
Use **Find a matching test** and confirm a suggestion based on date and caption.
The matching test must be completed and use the same platform. Linking creates one
workspace-scoped calibration outcome; repeating the import/link cannot duplicate
that outcome. For A/B tests, choose the matching variant in the picker.

Calibration shows errors for up to the last five model predictions made before
publication. Dry-run results and retrospective tests are excluded. View error is
expressed as percent of actual views; completion/watch errors use percentage
points. Historical views are not confused with simulated share intent.

A relative view estimate requires at least three linked model predictions on the
same platform, plus the current share-intent prediction. The median historical
ratio of actual views to predicted share intent scales the current estimate. This
is an uncertain observational estimate, especially if formats or observation
windows differ. Before enough evidence exists, results show the median baseline
and explain why a relative forecast is unavailable. No fixed "2×" claim is seeded.

## Privacy and later connectors

Imports, mappings, posts, originals and linked outcomes belong to one workspace.
They are not added to public accuracy datasets. Workspace admins can use **Delete
imported data**, with confirmation: it removes originals from local/S3 object
storage, import/post/mapping rows, associated calibration rows, imported audience
definitions and cached view forecasts. Existing tests and manual audience
definitions remain. An audit event records deletion without the imported content.

Automatic connectors are disabled by default (`KRUVIM_ANALYTICS_OAUTH_ENABLED=false`).
`services/analytics_connectors.py` defines a future adapter interface that validates
and writes the same tables as file import. No approved developer apps, credentials,
or new live OAuth network adapters are shipped. Existing configured social-account
features remain available for connected accounts; new setup controls are hidden
until the feature is enabled. LLM key defaults stay blank, and import needs no model.
