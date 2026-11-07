# World Monitor news connection

Data pool includes **World Monitor news**, using the documented authenticated
`/api/news/v1/list-country-headlines` endpoint. One hourly request covers the
configured audience countries. Publisher names, source links and original
publication times are retained. Articles older than 24 hours, future-dated items,
undated items and unavailable responses are excluded. UAE city references select
the matching emirate; country reporting is labelled as country context.

Set `KRUVIM_WORLD_MONITOR_API_KEY` on the API and worker server. Platform
administrators can alternatively save `world_monitor_api_key` through the existing
encrypted connector credentials control. Workspace credentials configure workspace
social listening. The shared news collector reads platform credentials.

The source starts pending. Before activating it, record the applicable World
Monitor agreement in Sources. The provider documents API Business or Enterprise
for customer-facing outputs and 30-day retention for attributed headlines.
Kruvim retains historical simulation evidence, so the agreement must cover that
retention before this source is approved. A credential alone does not activate it.

The hosted refresh route claims an hourly check through PostgreSQL before running
the connector. Normal worker installations also use the existing connector
scheduler. The Data Pool source gate applies to collection and simulation snapshots.

Verified with synthetic protocol, source-gating, storage, snapshot and scheduler
tests. Live collection requires the operator's subscription and API key.

Provider references are the [developer portal](https://www.worldmonitor.app/developers.md),
[API contract](https://www.worldmonitor.app/openapi.json), and
[subscription terms](https://www.worldmonitor.app/docs/eula).
