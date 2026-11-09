# Deploy Kruvim with Vercel Services

The repository root owns `vercel.json`. Import the GitHub repository and select the `landing-page` branch. Set the Vercel project root to the repository root (`.`), not either frontend directory. Vercel Services is currently in beta.

## Routing

| Service | Directory | Public paths |
| --- | --- | --- |
| `landing` | `landing-page/frontend` | `/`, the public `/app` entry page, and the final catch-all |
| `frontend` | `frontend` | `/app/*`, including `/app/register`, `/app/login`, `/app/home`, and app assets |
| `backend` | `backend` | `/api` and `/api/*` |

The most specific rewrites run first; the landing page owns the final catch-all. `/healthz`, `/readyz`, and `/metrics` at the domain root are not exposed as backend routes by this configuration. API routes already include `/api/v1`, and API docs are at `/api/docs`, so the backend prefix must not be stripped.

The frontend builds and runs locally with Vite's `/app/` base. React Router reads `import.meta.env.BASE_URL`, keeping client navigation and deep links under that path. Build files live under `dist/app/`, with `dist` as the service output directory, so public paths and artifact paths match without removing `/app`. Navigation requests such as `/app/projects/123` fall back to `/app/index.html`. The fallback excludes static assets, the favicon and Vite development-module paths so scripts, styles and fonts keep their own responses. The dev command uses Vercel's assigned `$PORT`.

## Calls and bindings

There are **no server-to-server calls between these three services** in the current application, so no unused bindings are declared:

- Browser JavaScript in the Vite app calls same-origin `/api/v1/*`. The public rewrite routes these requests to `backend`; it works on production and preview domains without hardcoded deployment hostnames.
- Browser JavaScript in the landing page calls the existing ANE Supabase Edge Function. Supabase is an external dependency, not a Vercel service in this repository.
- Backend links and OAuth callback URLs are public browser URLs, not internal service URLs.

A Vite bundle cannot consume runtime function bindings. Its existing `KRUVIM_API_URL` setting is only a standalone Vite development/preview proxy override; it is not needed for deployed browser requests. Docker Compose's `api`, `postgres`, and `redis` hostnames remain local to Docker and are not used by this Vercel configuration.

If a future Next.js Route Handler calls the backend, declare the binding on `landing` with all four fields (`type`, `service`, `format`, `env`) and read its URL at function runtime. Do not put the URL in a public variable, use it during builds, or manually set the binding variable.

## Environment and persistent infrastructure

`docs/vercel.env.example` lists the shared project environment variables. Enter their real values in Vercel, scoped to Preview and Production as appropriate. Provision separate preview data/resources so preview deployments do not alter production data. Never commit actual credentials.

The ANE project remains the landing page's Supabase project. Its signup schema and Edge Function are already deployed. Neither website deployment nor this configuration changes them.

The main FastAPI application also requires:

1. A persistent PostgreSQL database accessible from Vercel, with the existing backend Alembic migrations applied before serving traffic. If using ANE, use its PostgreSQL connection credentials, not the browser publishable key; confirm the migration target before running migrations.
2. A TCP Redis endpoint accessible from Vercel and the workers. The existing ARQ integration requires Redis protocol access, not a REST-only Redis URL.
3. S3-compatible object storage for uploads, with the bucket/endpoint/region and server-side AWS credentials available to both API and workers. Local files in a Vercel instance are temporary.
4. Separate long-running ARQ workers on a suitable host, sharing database, Redis and storage configuration. Run `arq app.workers.main.WorkerSettings` for simulations and `arq app.workers.connectors.ConnectorWorkerSettings` for connectors. The three-service configuration does not deploy these workers; leaving Redis unset would use in-process tasks, which cannot reliably survive function suspension.

The API uses the operating system's temporary directory on Vercel for scratch files and reproducible population caches. Production/preview startup rejects SQLite, absent Redis, absent S3 configuration, or development mode instead of silently using disposable state. This does not provision infrastructure or establish that workers are running.

Keep `KRUVIM_PUBLIC_URL` at the public **domain root**, for example `https://your-domain.example`, and `KRUVIM_APP_BASE_PATH=/app`. Browser invite/share links and post-OAuth redirects use the app path; provider callbacks stay at `/api/v1/social/{provider}/callback`. Production can use Vercel's generated domain if no explicit URL is configured. Preview links use the current deployment's `VERCEL_URL` rather than an inherited production URL. Register your exact production OAuth callback URLs with each provider before enabling social connections.

`KRUVIM_ENV=production` and a strong `KRUVIM_SECRET_KEY` are mandatory for Preview and Production. The API entrypoint is explicitly `app.main:app` relative to `backend/`.

Large video uploads currently pass through the API. Check Vercel's current function request-size and duration limits before launching that flow; the existing 500 MB Docker upload setting is not a Vercel platform allowance. Direct-to-storage uploads or another upload transport may be required. External workers need ffmpeg for video processing, as in the existing backend Dockerfile.

## Local testing

From the repository root, use the current Vercel CLI:

```powershell
npx vercel dev -L
```

This runs every service together without linking a cloud project. For local development, set `KRUVIM_PUBLIC_URL=http://localhost:3000`, `KRUVIM_APP_BASE_PATH=/app`, and the two public Supabase variables from the landing page environment example. Local SQLite and in-process workers remain available in development mode. Standalone Vite/Docker development keeps its existing root mount unless a base path is explicitly supplied.

Check `/`, the demo assets, `/app/login`, `/app/projects/123`, `/app/assets/*`, `/api/v1/healthz`, and `/api/docs`. Verify authenticated API calls, invites, shared reports and social redirects before a production deployment. `vercel dev` tests the shared routing table; a standalone Vite preview does not.

## Sources

- https://vercel.com/docs/services
- https://vercel.com/docs/services/routing
- https://vercel.com/docs/services/bindings
- https://vercel.com/docs/frameworks/backend/fastapi
