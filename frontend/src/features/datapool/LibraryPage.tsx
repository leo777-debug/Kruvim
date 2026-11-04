import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Page } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Card, Field, Input, Textarea } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { can, useAuth } from "@/lib/auth";

type Folder = { id: string; name: string; project_id: string | null; enabled: boolean; watch_enabled: boolean;
  rows: number; inbox_path: string | null; storage: string; database_schema: string; supabase_url: string | null; supabase_storage_url: string | null; sync_status: { at?: string; errors?: string[] } };
type Row = { id: string; title: string; data: string; region: string; language: string; tags: string; filename: string; revision: number };
type Draft = Pick<Row, "title" | "data" | "region" | "language" | "tags">;
type Preview = { headers: string[]; sample: Record<string, string>[]; rows: number };
const blank: Draft = { title: "", data: "", region: "*", language: "", tags: "" };
const selectStyle = "h-9 rounded-md border border-line bg-panel px-2 text-sm";

export default function LibraryPage() {
  const orgId = useAuth(s => s.orgId);
  // Remount on workspace changes so drafts and previews cannot cross customers.
  return <LibraryWorkspace key={orgId} orgId={orgId} />;
}

function LibraryWorkspace({ orgId }: { orgId: string | null }) {
  const cache = useQueryClient();
  const [selected, setSelected] = useState("");
  const [name, setName] = useState("");
  const [scope, setScope] = useState("");
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("");
  const folders = useQuery({ queryKey: [orgId, "library"], queryFn: () => api<Folder[]>("/library/folders") });
  const projects = useQuery({ queryKey: [orgId, "projects"], queryFn: () => api<{ id: string; name: string }[]>("/projects") });
  const folder = folders.data?.find(f => f.id === selected);
  async function refresh() { await cache.invalidateQueries({ queryKey: [orgId, "library"] }); }
  async function create() {
    setBusy(true);
    try {
      const f = await api<Folder>("/library/folders", { json: { name, project_id: scope === "shared" ? null : scope } });
      setSelected(f.id); setName(""); await refresh();
    } catch (e) { toast.error((e as Error).message); } finally { setBusy(false); }
  }
  return <Page wide title="Data library" subtitle="Keep customer research in folders. Type rows or import spreadsheets; new simulations automatically select matching evidence from shared folders and their own project's folders.">
    <div className="grid gap-5 lg:grid-cols-[260px_1fr]">
      <Card className="space-y-4 p-4 self-start">
        <h2 className="font-semibold">Folders</h2>
        {folders.isPending && <p role="status">Loading folders…</p>}
        {folders.isError && <p role="alert">{folders.error.message}</p>}
        {folders.data?.length === 0 && <p className="text-sm text-muted">Create a folder for a customer project, or a shared folder for common research.</p>}
        <nav aria-label="Library folders" className="space-y-1">{folders.data?.map(f => <button key={f.id} onClick={() => setSelected(f.id)} aria-current={selected === f.id ? "page" : undefined}
          className={`block w-full rounded-md p-2 text-left ${selected === f.id ? "bg-raised" : "hover:bg-raised"}`}>
          <span className="block font-medium">{f.name}</span><span className="text-xs text-muted">{f.rows} rows · {f.project_id ? projects.data?.find(p => p.id === f.project_id)?.name || "Project" : "Shared"}{!f.enabled && " · Paused"}</span>
        </button>)}</nav>
        {can("admin") && <div className="space-y-2 border-t border-line pt-4">
          <Field label="New folder name"><Input value={name} maxLength={160} onChange={e => setName(e.target.value)} placeholder="e.g. Cafe customer research" /></Field>
          <Field label="Use for"><select aria-label="Use for" className={selectStyle + " w-full"} value={scope} onChange={e => setScope(e.target.value)}>
            <option value="" disabled>Choose a project or shared</option><option value="shared">Shared — every project in this workspace</option>
            {projects.data?.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
          <Button onClick={create} disabled={!name.trim() || !scope} loading={busy}>Create folder</Button>
        </div>}
      </Card>
      {folder ? <FolderTable key={folder.id} folder={folder} orgId={orgId} filter={filter} setFilter={setFilter} refresh={refresh} />
        : <Card className="p-8 text-muted">Select a folder to view and edit its data. Use a separate project for each customer.</Card>}
    </div>
  </Page>;
}

function FolderTable({ folder, orgId, filter, setFilter, refresh }: { folder: Folder; orgId: string | null; filter: string;
  setFilter: (v: string) => void; refresh: () => Promise<void> }) {
  const cache = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>({ ...blank });
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const rows = useQuery({ queryKey: [orgId, "library", folder.id], queryFn: () => api<{ entries: Row[]; truncated: boolean }>(`/library/folders/${folder.id}/entries`) });
  async function perform(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    try { await action(); await refresh(); await cache.invalidateQueries({ queryKey: [orgId, "library", folder.id] }); toast.success(message); }
    catch (e) { toast.error((e as Error).message); } finally { setBusy(false); }
  }
  function uploadBody(isPreview: boolean, chosen = file) {
    const data = new FormData();
    if (chosen) data.append("file", chosen);
    data.append("preview", String(isPreview)); data.append("mapping", JSON.stringify(mapping));
    return data;
  }
  async function previewFile(chosen: File) {
    setBusy(true); setFile(chosen); setPreview(null); setMapping({});
    try { setPreview(await api<Preview>(`/library/folders/${folder.id}/import`, { method: "POST", body: uploadBody(true, chosen) })); }
    catch (e) { toast.error((e as Error).message); } finally { setBusy(false); }
  }
  const visible = rows.data?.entries.filter(r => `${r.title} ${r.data} ${r.tags} ${r.region}`.toLowerCase().includes(filter.toLowerCase())) || [];
  return <div className="min-w-0 space-y-4">
    <Card className="space-y-3 p-4">
      <h2 className="text-lg font-semibold">{folder.name}</h2>
      <p className="text-sm text-muted">Rows are supplied as background evidence, labelled as user supplied. They do not change population demographics. Saved rows apply when a new simulation prepares its audience; existing prepared tests keep their evidence.</p>
      {can("admin") && <div className="flex flex-wrap gap-4 text-sm">
        {([['enabled', 'Use in new simulations'], ['watch_enabled', 'Watch server inbox']] as const).map(([key, label]) => <label key={key} className="flex items-center gap-2">
          <input type="checkbox" checked={folder[key]} disabled={busy} onChange={e => perform(() => api(`/library/folders/${folder.id}`, { method: "PUT", json: {
            name: folder.name, project_id: folder.project_id, enabled: folder.enabled, watch_enabled: folder.watch_enabled, [key]: e.target.checked } }), "Folder updated")} />{key === 'watch_enabled' && folder.storage === 'supabase' ? 'Import from Supabase Storage' : label}</label>)}
      </div>}
      {folder.watch_enabled && <div className="space-y-2 rounded-md bg-raised p-3 text-sm">
        <p>{folder.storage === 'supabase' ? 'Upload CSV/XLSX files into this private Supabase Storage folder. Kruvim checks it on the cloud schedule and before preparing simulations.' : 'Place CSV/XLSX files here on the Kruvim server. The scheduler checks about every 10 minutes.'}</p>
        <code className="block break-all">{folder.inbox_path}</code>
        {folder.supabase_storage_url && <a className="block text-brand underline" href={folder.supabase_storage_url} target="_blank" rel="noreferrer">Open Supabase Storage</a>}
        <p>Use title, data, region, language and tags headers. Other columns are combined as data. Updating a filename replaces its imported rows. Removing a file does not delete saved rows.</p>
        {folder.sync_status.at && <p>Last checked: {new Date(folder.sync_status.at).toLocaleString()}</p>}
        {folder.sync_status.errors?.map(error => <p key={error} role="alert" className="text-neg">{error}</p>)}
        {can("admin") && <Button loading={busy} onClick={() => perform(() => api(`/library/folders/${folder.id}/sync`, { json: {} }), "Inbox checked")}>Check inbox now</Button>}
      </div>}
      {folder.supabase_url && <div className="rounded-md bg-raised p-3 text-sm space-y-2">
        <p>All workspace data lives in Supabase. To enter rows there, open Table Editor, select the <strong>{folder.database_schema}</strong> schema and <strong>library_entries</strong>. Use this folder ID:</p>
        <code className="block break-all">{folder.id}</code>
        <a className="text-brand underline" href={folder.supabase_url} target="_blank" rel="noreferrer">Open Supabase Table Editor</a>
      </div>}
    </Card>
    <Card className="space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <Input aria-label="Filter library rows" className="max-w-sm" placeholder="Search rows, tags or region" value={filter} onChange={e => setFilter(e.target.value)} />
        {can("member") && <label className="text-sm">Import CSV/Excel<input aria-label="Import CSV or Excel" className="ml-2 max-w-60" type="file" accept=".csv,.xlsx" disabled={busy} onChange={e => { const chosen = e.target.files?.[0]; if (chosen) void previewFile(chosen); e.target.value = ""; }} /></label>}
      </div>
      {preview && <div className="space-y-3 rounded-md border border-line p-3">
        <p className="font-medium">{file?.name} · {preview.rows} rows</p>
        <p className="text-sm text-muted">Map your columns, then import. Blank data mapping combines every nonempty cell. Reimporting the same filename replaces that file's rows, including edits to those rows.</p>
        <div className="flex flex-wrap gap-3">{Object.keys(blank).map(key => <label key={key} className="flex flex-col gap-1 text-sm">{key}<select className={selectStyle} value={mapping[key] || ""} onChange={e => setMapping({ ...mapping, [key]: e.target.value })}>
          <option value="">Automatic</option>{preview.headers.map(h => <option key={h} value={h}>{h}</option>)}</select></label>)}</div>
        <div className="max-h-48 overflow-auto"><table className="w-full text-left text-xs"><thead><tr>{preview.headers.map(h => <th key={h} className="p-2">{h}</th>)}</tr></thead><tbody>{preview.sample.map((r, i) => <tr key={i}>{preview.headers.map(h => <td key={h} className="max-w-64 truncate p-2">{r[h]}</td>)}</tr>)}</tbody></table></div>
        <Button variant="primary" loading={busy} onClick={() => perform(async () => { await api(`/library/folders/${folder.id}/import`, { method: "POST", body: uploadBody(false) }); setPreview(null); setFile(null); }, "Data imported")}>Import {preview.rows} rows</Button>
        <Button disabled={busy} onClick={() => setPreview(null)}>Cancel</Button>
      </div>}
      {rows.isPending && <p role="status">Loading rows…</p>}{rows.isError && <p role="alert">{rows.error.message}</p>}
      {rows.data?.truncated && <p>Showing the first 5,000 rows. Split large datasets across folders to manage them.</p>}
      <div className="max-h-[480px] overflow-auto"><table className="w-full text-left text-sm"><caption className="sr-only">Saved evidence in {folder.name}</caption>
        <thead className="sticky top-0 bg-panel"><tr>{["Title", "Data", "Region / language", "Tags", "Source", ""].map((h, i) => <th key={i} className="border-b border-line p-2">{h}</th>)}</tr></thead>
        <tbody>{visible.map(r => <tr key={r.id} className="border-b border-line align-top"><td className="p-2 font-medium">{r.title}</td><td className="min-w-52 max-w-xl whitespace-pre-wrap p-2">{r.data}</td><td className="p-2">{r.region}<br />{r.language}</td><td className="p-2">{r.tags}</td><td className="p-2 text-xs text-muted">{r.filename || "Typed row"}<br />Revision {r.revision}</td>
          <td className="p-2">{can("member") && <div className="flex gap-1"><Button size="sm" disabled={busy} onClick={() => { setEditing(r.id); setDraft({ title: r.title, data: r.data, region: r.region, language: r.language, tags: r.tags }); }}>Edit</Button>
            <Button size="sm" variant="danger" disabled={busy} onClick={() => { if (window.confirm(`Delete “${r.title}”? Prepared simulations keep their saved evidence.`)) void perform(() => api(`/library/folders/${folder.id}/entries/${r.id}`, { method: "DELETE" }), "Row deleted"); }}>Delete</Button></div>}</td></tr>)}</tbody>
      </table>{!rows.isPending && !visible.length && <p className="p-4 text-muted">No matching rows. Add data below or import a spreadsheet.</p>}</div>
    </Card>
    {can("member") && <Card className="space-y-3 p-4">
      <h3 className="font-semibold">{editing ? "Edit row" : "Type a new row"}</h3>
      <div className="grid gap-3 sm:grid-cols-2"><Field label="Title"><Input value={draft.title} maxLength={240} onChange={e => setDraft({ ...draft, title: e.target.value })} /></Field>
        <Field label="Tags / topics"><Input value={draft.tags} maxLength={500} onChange={e => setDraft({ ...draft, tags: e.target.value })} placeholder="coffee, Dubai, price research" /></Field>
        <Field label="Region (* = all)"><Input value={draft.region} maxLength={16} onChange={e => setDraft({ ...draft, region: e.target.value })} placeholder="AE-DXB" /></Field>
        <Field label="Language (blank = all)"><Input value={draft.language} maxLength={20} onChange={e => setDraft({ ...draft, language: e.target.value })} placeholder="en, ar, ml…" /></Field></div>
      <Field label="Data / observation"><Textarea value={draft.data} rows={4} maxLength={10000} onChange={e => setDraft({ ...draft, data: e.target.value })} placeholder="Enter the research finding, product detail, customer preference or survey result. Include its source and date when available." /></Field>
      <Button variant="primary" loading={busy} disabled={!draft.title.trim() || !draft.data.trim()} onClick={() => perform(async () => { await api(`/library/folders/${folder.id}/entries${editing ? '/' + editing : ''}`, { method: editing ? "PUT" : "POST", json: draft }); setDraft({ ...blank }); setEditing(null); }, "Row saved")}>{editing ? "Save changes" : "Save row"}</Button>
      {editing && <Button disabled={busy} onClick={() => { setEditing(null); setDraft({ ...blank }); }}>Cancel edit</Button>}
    </Card>}
  </div>;
}
