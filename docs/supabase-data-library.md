# Supabase application database and research library

Kruvim's hosted application uses the existing **ANE** Supabase project (`jrdgxbdglmpynbyfmamf`). Its entire application database is in the private **kruvim** schema. The pre-existing public tables and landing-page forms remain separate. The application's users, workspaces, projects, simulations, reports, population metadata, research rows, job queue and controls are persisted in Supabase PostgreSQL. Uploaded files are in the private **kruvim-data** Supabase Storage bucket. Local temporary files are derived caches or processing scratch space.

The app is at **https://kruvim-lp.vercel.app/app/**. Create an account, open **Data library**, and create a folder for a customer project or explicitly share it across your workspace. The folder displays its ID and Supabase Storage path.

## Enter or import rows directly in Supabase

1. Open https://supabase.com/dashboard/project/jrdgxbdglmpynbyfmamf/editor.
2. Select the **kruvim** schema, then **library_entries**.
3. Insert rows or import a CSV. Include `folder_id`, `title` and `data`; optionally include `region`, `language` and `tags`.
4. Copy `folder_id` from that customer's folder in Kruvim. Other fields have database defaults: IDs/source keys generate automatically, region defaults to `*`, language/tags/filename to empty strings, and revision to 1.

These are live database rows. New simulation preparation queries them directly. No file synchronization is needed for table edits. Keep each customer's tests in the project assigned to their folder. Shared folders are explicitly available to every project in that workspace. Workspace membership grants access to the workspace's library; use separate workspaces for separate customer login permissions.

## Upload CSV/XLSX in Supabase Storage

Open https://supabase.com/dashboard/project/jrdgxbdglmpynbyfmamf/storage/buckets and choose **kruvim-data**. Create/use the path shown by Kruvim: `library-inbox/<workspace-id>/<folder-id>/`. Upload files directly inside that directory. Use `title,data,region,language,tags` headings; other columns are combined as research text. The hosted app also accepts uploads and typed rows through Data library.

Supabase Cron invokes the hosted importer every ten minutes. **Check inbox now** imports immediately, and simulation preparation also checks the current workspace's enabled inboxes. Content hashes avoid repeat imports. Updating a filename atomically replaces that file's saved rows while retaining manual rows; errors preserve the previous valid import. Deleting a Storage file does not delete already imported rows. Pause the folder to exclude it from new simulations.

Files are bounded to 10 MB, 5,000 rows and 50 columns; XLSX uses the first worksheet, with a 50 MB expanded limit. Export formulas as values. These inputs are research evidence; statistical population calibration stays in Survey data.

## Selection and saved evidence

Kruvim filters enabled folders by workspace and simulation project, matches the request/content words, then filters by the simulated person's region and language. Up to three matching rows per person are frozen with row ID, source, folder and revision. The model receives at most 1,500 characters per selected row, labelled as unverified user-supplied research. Later edits affect new preparations; existing prepared tests retain the evidence they used. Dry runs record evidence but do not interpret it through a language model.

## Hosted operation

Vercel hosts the landing page, frontend and FastAPI service. It reads the existing Supabase integration's `POSTGRES_URL` and server-side Supabase credentials. Serverless deployments reject SQLite. SQLAlchemy qualifies application tables with the `kruvim` schema and uses Supabase's pooler. The migration head is `0017`; future migrations must use the configured schema. A dedicated Supabase migration created the fresh cloud schema and imported existing local records. Existing uploads were byte-verified after transfer; the known demo login was disabled in the cloud copy.

Durable jobs live in `kruvim.cloud_jobs`. pg_net delivers authenticated calls to the hosted worker route after enqueue commits. Live events and simulation controls are read from Supabase across instances. Supabase Cron runs `kruvim-cloud-imports`; its authentication token is in Supabase Vault and Vercel's sensitive environment variables. Requests share the hosting function duration limit (currently 300 seconds per stage); unusually long model stages still require a longer-running worker deployment.

Application tables are outside exposed public schemas, have RLS enabled, and grant no access to anonymous/browser roles. Private Storage uses backend credentials. Supabase project administrators can manage the data through the dashboard; Kruvim enforces workspace roles through its API. Never put server credentials into frontend variables.
