# Deploying the Kruvim beta

This guide takes a fresh server to an invite-only beta. It uses the Docker Compose stack in this repository:
- PostgreSQL with pgvector;
- Redis;
- the API;
- background workers;
- the web app behind nginx;
- daily backups.

> **Supabase.** Moving the database, file storage, sign-in and key storage to Supabase is planned as the final phase. Nothing here blocks that move: the stack already uses Postgres with pgvector and S3-compatible storage.

## 1. What you need

- **A Linux server** with Docker and the Compose plugin. 4 vCPU and 8 GB RAM is comfortable for a beta. The synthetic population uses about 1 GB.
- **A domain name**, and HTTPS in front of the stack: Caddy, Cloudflare or a cloud load balancer.
- **Optional:** a model-provider key for the shared beta key. Without one, workspaces use dry run or their own keys.
- **Optional:** an S3-compatible bucket (AWS S3, Cloudflare R2, Supabase Storage) for uploaded files.
- **Optional:** a Sentry project.

## 2. Configure

```bash
cp .env.example .env
```

Set at least these in `.env`:

| Setting | Value |
|---|---|
| `KRUVIM_SECRET_KEY` | A long random string: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. It signs sessions and encrypts stored keys. **Back it up**: losing it means losing every stored provider key. |
| `POSTGRES_PASSWORD` | A strong password |
| `KRUVIM_PUBLIC_URL` | `https://your-domain` |
| `KRUVIM_CORS_ORIGINS` | `https://your-domain` |
| `KRUVIM_FIRST_SUPERUSER_EMAIL` / `KRUVIM_FIRST_SUPERUSER_PASSWORD` | Your platform-admin account, created on first start. Signing up first never makes anyone an admin in production. |
| `KRUVIM_ALLOW_REGISTRATION` | `false` for an invite-only beta (this is the default in Compose) |

## 3. Start

```bash
docker compose up -d --build
```

```bash
curl -fsS http://localhost:8080/readyz
```

The `migrate` service applies database migrations before the API starts. Every upgrade is the same `docker compose up -d --build`.

## 4. HTTPS

The bundled nginx listens on `KRUVIM_HTTP_PORT` (default 8080). Put an HTTPS proxy in front of it. For example, with Caddy:

```
your-domain {
    reverse_proxy localhost:8080
}
```

- **Proxy count:** `KRUVIM_FORWARDED_HOPS` is the number of proxies in front of the API. The default of 1 is the bundled nginx. **Add one for each proxy in front of it**; Caddy alone makes it 2. If this is wrong, per-IP rate limits apply to your proxy instead of to visitors.
- **Security headers** (HSTS, CSP and others) are already sent by nginx. HSTS takes effect once the site is served over HTTPS.

## 5. First steps after launch

1. **Sign in** with the first-superuser account and open **Platform admin**.
2. **Shared model key** (optional): under **Platform model key**, choose the provider and models and enter the key. Workspaces without their own key use it, metered in credits. Daily caps:
   - `KRUVIM_PLATFORM_DAILY_CALL_LIMIT`: all workspaces together;
   - `KRUVIM_ORG_DAILY_CALL_LIMIT`: each workspace.

   Set them from your budget: daily budget ÷ average cost per call.
3. **Invite beta users:** under **Beta invites**, create codes. A code can be limited to one email, used several times, and set to expire. Send the sign-up link it shows (`/register?code=…`). Partners can skip codes via `KRUVIM_SIGNUP_ALLOWLIST=@partner.com,person@x.com`. Workspace admins invite teammates from Settings → Members.
4. **Legal pages:** fill in the company name, address, contact email and jurisdiction in `frontend/src/features/legal/LegalPages.tsx` (the `LEGAL` object), then rebuild. Until then both pages say they are drafts. **Have counsel review them before a public launch.**
5. **Track record:** forecasts live under Advanced → Track record. The public hash ledger (`/api/v1/public/ledger`) is always on. The public scoreboard at `/record` stays off until `KRUVIM_PUBLIC_TRACK_RECORD=true`.

## 6. Backups and restore

**What's backed up.** The `backup` service writes into the `backups` Docker volume:
- a PostgreSQL dump: `db-YYYYmmdd-HHMMSS.dump`;
- an archive of uploaded files: `files-….tar.gz`.

It runs every `KRUVIM_BACKUP_INTERVAL_HOURS` (default 24) and keeps `KRUVIM_BACKUP_KEEP_DAYS` days (default 14). `last-run` holds the time of the last run.

**Copy backups off the server.** A backup on the same disk doesn't survive losing the server. For example, a nightly cron job with rclone:

```bash
docker run --rm -v kruvim_backups:/backups -v ~/.config/rclone:/config/rclone rclone/rclone copy /backups remote:kruvim-backups
```

If files are stored in a bucket (`KRUVIM_STORAGE_BACKEND=s3`), turn on bucket versioning instead of relying on the file archive.

**Restore** into a stopped stack:

```bash
docker compose stop api worker connector-worker
docker compose cp backup:/backups/db-<stamp>.dump ./restore.dump   # or copy it in from off-site storage
docker compose exec -T postgres pg_restore -U kruvim -d kruvim --clean --if-exists < ./restore.dump
docker compose up -d
```

Uploaded files: extract `files-<stamp>.tar.gz` into the `kruvim-data` volume (it contains `objects/`).

**Practise a restore before launch.** A backup that has never been restored is a hope, not a backup.

## 7. Monitoring

- **Uptime:** point an uptime monitor (UptimeRobot, Better Stack, a cloud health check) at `https://your-domain/api/v1/readyz`. It checks the database and Redis.
- **Errors:** Platform admin → **Errors** shows the last 30 days:
  - unexpected server errors, each with the reference the user saw;
  - background-job crashes;
  - browser errors.

  Keys and tokens are removed before anything is stored. **Failed jobs** lists simulations and reports that stopped.
- **Sentry (optional):** set `KRUVIM_SENTRY_DSN`. Personal data, request bodies, cookies and headers are never sent.
- **Logs:** run `docker compose logs -f api worker`. Logs are JSON lines with a `request_id`; quote it to find one request.
- **Metrics:** Prometheus metrics are served at `/metrics` *inside* the Docker network. nginx blocks them publicly.
- **Usage:** Platform admin → **Usage** shows calls, tokens and cost per workspace this month, and today's calls on the shared key.

## 8. Operations

- **Disable an account:** Platform admin → Users → Disable. They are signed out everywhere immediately.
- **Rotate the secret key:**
  1. Move the old value to `KRUVIM_PREVIOUS_SECRET_KEYS`.
  2. Set a new `KRUVIM_SECRET_KEY` and deploy.
  3. Run `docker compose exec api python -m scripts.rotate_secrets`.
  4. Remove the old key.

  Everyone is signed out.
- **Scale simulations:** `docker compose up -d --scale worker=4`.
- **Local models** (self-hosted only): `docker compose --profile local-llm up -d`, then set `KRUVIM_ALLOW_PRIVATE_MODEL_URLS=true`. Never enable this on a shared, multi-customer server: it lets workspace admins reach internal network addresses.

## 9. Settings reference

All settings are environment variables in `.env`. Defaults shown are the application's; Compose overrides a few.

**Core**

| Setting | Default | Purpose |
|---|---|---|
| `KRUVIM_ENV` | development (Compose: production) | `production` enables the strict defaults below |
| `KRUVIM_SECRET_KEY` | — (required) | Signs sessions and encrypts stored secrets |
| `KRUVIM_PREVIOUS_SECRET_KEYS` | empty | Old keys still accepted for decryption during rotation |
| `KRUVIM_PUBLIC_URL` | http://localhost:5173 | Used in invite, share and sign-up links |
| `KRUVIM_CORS_ORIGINS` | localhost | Allowed browser origins, comma separated |
| `KRUVIM_DATABASE_URL` / `KRUVIM_REDIS_URL` | SQLite / none (Compose sets both) | Database and job queue |
| `KRUVIM_DATA_DIR` | ./data (Compose: /data) | Population files and local uploads |
| `KRUVIM_STORAGE_BACKEND`, `KRUVIM_S3_BUCKET`, `KRUVIM_S3_ENDPOINT_URL`, `KRUVIM_S3_REGION` | local | Store uploads in an S3-compatible bucket instead |
| `KRUVIM_MAX_UPLOAD_MB` | 500 | Largest upload |

**Access and security**

| Setting | Default | Purpose |
|---|---|---|
| `KRUVIM_ALLOW_REGISTRATION` | open in development, closed in production | Open sign-up without an invite code |
| `KRUVIM_SIGNUP_ALLOWLIST` | empty | Emails or `@domains` that can always sign up |
| `KRUVIM_FIRST_SUPERUSER_EMAIL` / `_PASSWORD` | empty | Platform admin created on start |
| `KRUVIM_ACCESS_TOKEN_MINUTES` / `KRUVIM_REFRESH_TOKEN_DAYS` | 30 / 14 | Session lengths |
| `KRUVIM_FORWARDED_HOPS` | 0 (Compose: 1) | Proxies in front of the API |
| `KRUVIM_RATE_LIMIT_PER_MINUTE` / `_AUTH_PER_MINUTE` | 240 / 20 | General and sign-in request limits |
| `KRUVIM_RATE_LIMIT_EXPENSIVE_PER_MINUTE`, `_RUNS_PER_HOUR`, `_UPLOADS_PER_HOUR` | 20 / 30 / 60 | Per-user limits on expensive actions |
| `KRUVIM_ALLOW_PRIVATE_MODEL_URLS` | on in development, off in production | Allow model servers on private addresses (self-hosted only) |
| `KRUVIM_SENTRY_DSN` | empty | Optional error monitoring |

**Models and spending**

| Setting | Default | Purpose |
|---|---|---|
| `KRUVIM_LLM_PROVIDER`, `_PRESET`, `_BASE_URL`, `_API_KEY`, `_VOICE_MODEL`, `_REPORT_MODEL`, `_VISION_MODEL`, `_CONCURRENCY` | dry run | Shared key from the environment. Setting it under Platform admin is preferred. |
| `KRUVIM_PLATFORM_DAILY_CALL_LIMIT` | 20,000 | Shared-key calls per day, all workspaces |
| `KRUVIM_ORG_DAILY_CALL_LIMIT` | 3,000 | Shared-key calls per day, per workspace |
| `KRUVIM_JOB_MAX_LLM_CALLS` | 20,000 | Ceiling for any single job, any key |
| `KRUVIM_RUN_CALL_CAP_FACTOR` | 1.5 | A run may use this multiple of its estimate |
| `KRUVIM_EMBEDDING_MODEL`, `KRUVIM_EMBEDDING_PRICE_PER_MILLION` | empty | Optional provider embeddings (local embeddings otherwise) |

Workspace admins set their own monthly and per-member limits in Settings → Spending limits.

**Simulation and data**

| Setting | Default | Purpose |
|---|---|---|
| `KRUVIM_POPULATION_SIZE` / `_SEED` | 1,000,000 / 7 | Synthetic population |
| `KRUVIM_WORKER_MAX_JOBS` | 4 | Jobs per worker process |
| `KRUVIM_SIMULATION_MAX_DURATION_SECONDS` | 7,200 | A run is stopped after this long |
| `KRUVIM_ORG_MAX_CONCURRENT_DEFAULT` | 2 | Default concurrent runs per workspace (plans override it) |
| `KRUVIM_BAROMETER_EXCERPTS` | 6 | Barometer passages given to each simulation |
| `KRUVIM_PUBLIC_TRACK_RECORD` | false | Publish the scoreboard at `/record` |
| `KRUVIM_BACKUP_INTERVAL_HOURS` / `_KEEP_DAYS` | 24 / 14 | Backup service |

**Data connectors (optional).** These are needed only for the matching live sources:
- `KRUVIM_REDDIT_CLIENT_ID/SECRET`
- `KRUVIM_YOUTUBE_API_KEY`
- `KRUVIM_X_BEARER_TOKEN`
- `KRUVIM_BLUESKY_HANDLE/APP_PASSWORD`
- `KRUVIM_OPEN_METEO_API_KEY`
- `KRUVIM_YOUTUBE|TIKTOK|INSTAGRAM_CLIENT_ID/SECRET`, `KRUVIM_ANALYTICS_OAUTH_ENABLED` (creator analytics)

**Tuning** (defaults are fine):
- `KRUVIM_DATAPOOL_REFRESH_MINUTES`
- `KRUVIM_SOCIAL_SYNC_MINUTES`
- `KRUVIM_CONNECTOR_*`
- `KRUVIM_SNAPSHOT_ARCHIVE_DAYS`
- `KRUVIM_SIGNAL_MAX_AGE_HOURS`
- `KRUVIM_ACCURACY_MIN_*`
- `KRUVIM_SOURCE_WEIGHT_MIN_TESTS`
- `KRUVIM_DB_POOL_SIZE` / `_MAX_OVERFLOW`

## 10. Before you invite people

- [ ] `.env` has a real secret key, strong passwords, your domain and `KRUVIM_ALLOW_REGISTRATION=false`.
- [ ] The site is served over HTTPS and `KRUVIM_FORWARDED_HOPS` matches your proxies.
- [ ] `/readyz` is monitored; Sentry is set if you use it.
- [ ] Backups are copied off the server, and you have **done one test restore**.
- [ ] The legal pages have your company details and have been reviewed.
- [ ] Shared-key daily limits match your budget, or the shared key is not set.
- [ ] You have created invite codes and signed up with one yourself.
