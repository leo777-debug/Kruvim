# Selective activation

New tests use an initial sample of 40 voices and at most 20 active speakers per round.
Under More options > Depth, set Maximum active speakers per round (1-256) and Initial reaction sample (10-2,000). Regional local-hour curves, per-agent activity and reply wakeups determine eligibility before seeded selection is capped. Unsampled speakers remain eligible in later rounds. Sampling does not remove speakers or guarantee everyone will act.

API fields: overrides.active_per_round and overrides.initial_reaction_sample. Omit both for legacy behavior. Estimates, validation and execution share the same policy. Results include activation_policy and observed round activity.

Example: 100 voices, no stakeholders, 10 hours, 60 minutes per round, initial sample 40, active cap 20. At most 200 discussion turns plus 40 initial impressions. This is not a 240-request hard budget: tools, retries, A/B variants, graph construction, memory and reports add calls. Existing token and spend controls remain authoritative. USD estimates remain unknown if provider prices are not configured.

The million-person population is a statistical projection. Speaker and worker capacity limits still apply; this change does not provision a million independently speaking models.
