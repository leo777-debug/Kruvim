# Reliable background processing

Hosted HTTP functions do not execute simulation stages. The previous 270-second
stage deadline cannot accommodate the supported long simulations and bulk surveys;
no paid workload fit within that limit has been certified. The API now requires
external Redis/arq workers for hosted jobs and returns 503 when Redis is not configured.
The legacy HTTP job handler also rejects hosted execution.

## Deployment

Run the existing backend image as three persistent services (not HTTP functions):

```
arq app.workers.main.WorkerSettings
arq app.workers.connectors.ConnectorWorkerSettings
arq app.workers.main.MaintenanceWorkerSettings
```

Set `KRUVIM_REDIS_URL` to the same durable Redis instance on the hosted API and all
workers. Use persistence and `noeviction`; the repository's Docker Compose stack
already configures these. Set the workers' `KRUVIM_SERVERLESS=false`,
`KRUVIM_ENV=production`, `KRUVIM_DATABASE_URL`, `KRUVIM_DATABASE_SCHEMA`,
`KRUVIM_SECRET_KEY`, storage settings and provider credentials to the same values as
the API. Workers need access to the same durable database and storage. Explicitly
configure the database URL on external workers; Vercel's automatic POSTGRES_URL
mapping only runs inside Vercel. Use the connection URL/TLS requirements supplied
by your database host. Do not run the full local Compose stack against production:
its default database and Redis are local services.

Set `KRUVIM_SIMULATION_MAX_DURATION_SECONDS=7200` consistently on API and workers
(the new default), removing any previous 270-second override. The worker timeout
is at least six hours and always exceeds the configured stage deadline. This is a
bounded runtime, not a guarantee every provider or workload completes within it.

Check the services with `arq app.workers.main.WorkerSettings --check` and
`arq app.workers.connectors.ConnectorWorkerSettings --check`, plus
`arq app.workers.main.MaintenanceWorkerSettings --check`.
The Compose services already use these health checks and restart policies.

## Maintenance

The dedicated maintenance worker dispatches maintenance every minute and at startup. The
authenticated `/api/v1/internal/refresh` endpoint dispatches the same schedule;
it never performs maintenance inside the HTTP request. It returns 503 without
Redis. Keep an existing one-minute HTTP cron as an additional dispatcher if desired;
the maintenance worker scheduler runs without it. Its separate queue keeps simulation
traffic from occupying maintenance capacity. Both paths use the same per-slot Redis job
IDs and retain results for two days, preventing duplicate dispatch within a slot.
After an outage, dispatch resumes with the latest slot instead of replaying every
missed interval. Individual failures remain visible in worker logs/results and do
not stop other maintenance jobs from running.

| Task | Schedule (UTC) |
| --- | --- |
| Data refresh, library inbox, all enabled due connectors | Every 10 minutes |
| Recurring simulations and monitoring | Every 10 minutes, offset 5 |
| Creator analytics sync | Every 10 minutes, offset 3 |
| Cultural synthesis and archive compression | Hourly at :15 |
| Agent memory consolidation | Daily at 02:30 |
| Run watchdog and token budget maintenance | Separate jobs every minute |
| Public context snapshot archive | Every 10 minutes, offset 1 |

Due connectors run on the dedicated connector queue. Data-source approval and
configured connector intervals still apply. A successful refresh response confirms
queue dispatch, not worker health or successful execution.

Before switching an existing hosted deployment, inspect pending/running legacy
`cloud_jobs` entries. Let active HTTP executions stop, then retry affected stages
through the application after all external workers are healthy. Legacy jobs are
not replayed automatically because replaying completed provider calls may charge
again. Simulation controls continue through the shared database/Redis modes as
appropriate; make the queue switch during a quiet period.

This change supplies code and deployment instructions. External services must be
provisioned and deployed before production background processing is operational.
