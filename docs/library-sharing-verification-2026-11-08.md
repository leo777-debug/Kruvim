# Library sharing verification — 8 November 2026

The Data Library now separates opt-in Public contributions from workspace-private uploads. Simulation research mode independently selects admin + workspace evidence, or admin + workspace + community evidence. Data Pool is reserved for platform administrators.

## Verified locally

- 12 existing library/cloud checks passed, including atomic imports, project/workspace isolation, frozen evidence, cloud dispatch and Alembic upgrade/downgrade through revision 0018.
- 18 visibility and agent-memory checks passed. Six new visibility checks were repeated successfully after the final memory change.
- Both Private and Public full dry-run workflows completed graph → environment → simulation → report. Each voice agent received the expected evidence groups. Mode survived cloning; changing mode invalidated prepared state.
- Public creation requires acknowledgement. Private folders are absent from other workspaces, public folders are readable but cannot be edited by other workspaces, unpublishing removes future community access, and ordinary workspace owners cannot create baseline data or access pool management APIs.
- Members can contribute to the same workspace's library; admin baseline mutations remain restricted to platform administrators.
- Public and Private memory snapshots do not recall each other's experiences. Agent follow-up detail and recalled memory use the same mode filter, with a dedicated regression assertion. Creator summaries and familiarity subjects are separated by research mode.
- Frontend production build and navigation checks passed. Data Pool has no regular-user sidebar entry; direct navigation redirects to Data Library.
- Four desktop/mobile browser cases passed across typed rows, editing, CSV import, persistence, explicit publishing, another workspace's read-only view, absence of private rows and mode selection. A mobile test initially reused a community folder name across projects; unique names fixed the test ambiguity. Edge was used because this checkout's Playwright browser revision was not cached.
- React review: workspace/mode-specific query keys, reset selection on tab changes, private defaults, labelled publishing acknowledgement, read-only action gating, accessible mode selection and mobile overflow checks.

## Hosted migration and release

The additive migration adds a constrained `visibility` column, defaulting to `private`. It does not change table grants, RLS, bucket access or login records. Pre-migration inspection confirmed revision 0017, three folders, 69 rows, RLS enabled on both library tables, and no `kruvim` schema usage for browser `anon`/`authenticated` roles.

After migration, confirm revision 0018, all 69 original rows still in Private folders, and both RLS/grants unchanged. Check production deployment SHA, readiness, app assets, the exposed API contract and unauthenticated library denial. Browser scenarios above use an isolated database and synthetic accounts; no hosted customer account or real model API is used for those tests.

The security advisor's existing no-policy INFO notice is intentional for these server-only tables: browser roles have no schema access, and the application API enforces ownership/visibility. No browser RLS policy or public storage bucket is introduced for community sharing.
