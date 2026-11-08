# Public and Private research

All Data Library rows remain in Kruvim's Supabase database. Visibility controls access through Kruvim; sharing does not provide Supabase logins, keys or direct table access.

## Contributions

- **Private** is the default. Members of the same workspace can add and edit rows. Folders can apply to one project or every project in that workspace. A new workspace starts with an empty private library.
- **Public** folders are available to all signed-in Kruvim users. Publishing a folder or creating a public folder requires an explicit acknowledgement. Every later row or import into that folder is also public. Other workspaces can read contributions but cannot edit them. Only the contributing workspace can change the folder and its rows.
- **Admin baseline** folders are maintained by platform administrators and available to the simulation engine in both research modes. They are not listed in customers' private or public tabs. Existing approved background feeds continue to supply regional context.

Existing folders migrate to Private. No historical customer upload is published automatically. The 69 existing production rows remain private. Existing official data can be intentionally contributed later through the Public option; a platform administrator can add curated reference data through Admin baseline.

Publishing a project-specific folder removes its project restriction, because public contributions apply across projects. Making a public folder Private excludes it from future community retrieval. Evidence already frozen in a prepared simulation is retained; previously shared data cannot be recalled from those copies.

## Simulation evidence

The creator form has a separate **Library mode** selector:

| Mode | Available research |
| --- | --- |
| Private | Admin baseline + the workspace's matching project and common folders, including its own public contributions |
| Public | Admin baseline + the workspace's matching data + public contributions from other workspaces |

Private is the default for old and new simulations. Choosing Public does not publish the scenario, private uploads or results. Mode survives preparation, edits and cloning. Changing mode invalidates the prepared state and requires preparation again.

Retrieval filters by relevance, geography and language. Each voice agent receives at most three library rows. Where relevant rows exist, retrieval reserves a place for admin baseline, the workspace and, in Public mode, community evidence. More data is not a guarantee of broader or representative opinion. Research is labelled as unverified data rather than instructions, and it does not automatically recalibrate population weights. Dry-run mode stores evidence but does not interpret it with an AI model.

New agent memory recall and creator summaries are separated by research mode so a Public run's experience is not carried into a later Private run. Historical runs without a mode are treated as Private.

## Access boundaries

Data Pool navigation and direct page access are reserved for platform administrators. Workspace owners and admins use Data Library. Pool connectors, raw signals, datasets and listening management endpoints also require platform administration. Population audience-count APIs and regional context summaries remain available to the simulation flow.

Public is an application visibility setting, not a PostgreSQL `public` schema or public Supabase bucket. The `kruvim` schema remains inaccessible to browser `anon` and `authenticated` roles, with RLS enabled on library tables. API write queries always require ownership of the contributing workspace; admin baseline writes additionally require platform administrator status.

## Schema

Alembic revision `0018` adds `library_folders.visibility`, default `private`, with constraints for accepted values and global scope for public/baseline folders. No new Supabase grants or policies are required; authenticated application API requests enforce the sharing rules.
