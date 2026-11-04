# Customer data library

The hosted app now uses Supabase for the complete application database and private file storage. Follow [the Supabase workflow](supabase-data-library.md) for the deployed setup. The server-folder notes below describe the optional local-development mode.

Open **Data library**. An owner/admin creates a folder and explicitly assigns it to a customer project or shares it across the current workspace. Members can import, type, edit and delete rows; viewers can read. Workspace membership grants access to all library folders in that workspace. Use separate workspaces if customers must not see one another's data; project scoping controls simulation selection, not member permissions.

Each row has a title, data, region (`*` for all), optional language code and tags. CSV and XLSX uploads show a preview and optional column mappings. With no mapped data column, nonempty cells are combined as `column: value`. First worksheet only; 10 MB compressed / 50 MB expanded, 50 columns, 5,000 rows per file; Excel formulas must be exported as values. Supported regions match Data pool regions. These rows are research evidence, not demographic calibration inputs.

Reimporting the same filename in the same folder replaces its rows in one transaction. Removed rows in that file disappear, manual rows survive, changed values increment revisions. Edits to imported rows are overwritten on the next import of that filename. Different filenames append datasets. Original uploaded files are parsed in memory; evidence rows and source filenames are retained in the database.

## Recurring server folder

Enable **Watch server inbox**. The UI shows the server directory under `KRUVIM_DATA_DIR/library-inbox/<workspace-id>/<folder-id>`. Place CSV/XLSX files directly in it (no subdirectories). Use `title,data,region,language,tags` column headings for predictable automatic mapping. Arbitrary columns are retained as combined text. Do not copy files while the importer is reading: write to a temporary extension then rename atomically. Symlinks are skipped. Files are limited to 100 per folder per scan.

The existing Data pool scheduler scans enabled inboxes approximately every ten minutes, using the API's local scheduler or the normal Redis worker. **Check inbox now** runs immediately. Content hashes skip unchanged files. Invalid replacements preserve the previous valid dataset and show an error. Removing a server file leaves the saved dataset intact; delete unwanted rows in the UI. A later changed import recreates deleted rows. Pausing a folder excludes it from new retrieval and scheduled scans.

This watches a directory on the application server. It does not automatically connect to a user's local Excel, OneDrive, Dropbox or Google Drive. A sync/connector must deliver files into the server directory. The inbox needs persistent storage shared by API and workers; this is especially important with containers. It is separate from S3 upload storage.

## Simulation selection

When a simulation prepares its audience, it reads enabled shared folders and folders assigned to that simulation's project, always within its workspace. Use a separate project per customer and start the test in that project. Rows match words in the simulation request and content card, then region/language filters select up to three per simulated voice agent. Ranking is deterministic lexical matching, without extra model calls. At most 25,000 candidate rows are considered in stable ID order. Unmatched rows are excluded. This is contextual evidence selection, not an automatic statistical fit of all imported observations.

Selected row IDs, data, source filename, folder and revision are frozen in agent `personal_signals`, with a distinct `workspace_library` source and an unverified user-supplied provenance label. Model reaction prompts receive at most 1,500 characters per selected row, marked as data rather than instructions. Existing prepared simulations retain their evidence after library edits or deletion; prepare a new test to use updated rows. Deterministic dry-run mode records evidence but does not interpret research text.

## Deployment

Run `python -m alembic upgrade head` from the backend to apply migration `0016`, deploy the backend and frontend, and restart the normal scheduler/workers. No external credentials are required. This implementation does not publish or deploy itself.
