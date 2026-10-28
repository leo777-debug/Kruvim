import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Download, FileText, Search, Trash2, Upload } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Page } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Badge, Callout, Card, CardHeader, Empty, Field, Input, Skeleton } from "@/components/ui/primitives";
import { api, ApiError, downloadFile } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt } from "@/lib/utils";

interface BarometerDoc {
  id: string; title: string; country: string; publisher: string; source_url: string | null; published_on: string | null;
  filename: string; size: number; status: "ready" | "quarantined"; quarantine_reason: string | null; chunk_count: number;
  text_chars: number; encoding: string | null; created_at: string; scope: "shared" | "workspace";
}
interface Excerpt { chunk_id: string; document_id: string; title: string; publisher: string; country: string; published_on: string | null; location: string; text: string; scope: string }

const ACCEPT = ".csv,.tsv,.xlsx,.json,.pdf,.docx,.txt,.md,.html,.htm,.xml";
const blank = { country: "", publisher: "", title: "", source_url: "", published_on: "", shared: false };

export default function BarometersPage() {
  const orgId = useAuth((s) => s.orgId);
  const isAdmin = useAuth((s) => !!s.user?.is_superuser);
  const qc = useQueryClient();
  const list = useQuery({ queryKey: [orgId, "barometers"], queryFn: () => api<{ documents: BarometerDoc[]; countries: Record<string, number> }>("/barometers") });
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [f, setF] = useState(blank);
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Excerpt[] | null>(null);
  const [searching, setSearching] = useState(false);

  async function upload(e: FormEvent) {
    e.preventDefault();
    if (!file) return toast.error("Choose a file first.");
    const fd = new FormData();
    fd.append("file", file);
    Object.entries(f).forEach(([k, v]) => fd.append(k, String(v)));
    setBusy(true);
    try {
      const d = await api<BarometerDoc>("/barometers", { method: "POST", body: fd });
      if (d.status === "quarantined") toast.warning(`Saved but quarantined: ${d.quarantine_reason}`);
      else toast.success(`Added "${d.title}" (${fmt.n(d.chunk_count)} passages indexed)`);
      setFile(null); setF({ ...blank, country: f.country, publisher: f.publisher });
      if (fileRef.current) fileRef.current.value = "";
      qc.invalidateQueries({ queryKey: [orgId, "barometers"] });
    } catch (ex) {
      toast.error(ex instanceof ApiError ? ex.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  }

  async function search(e: FormEvent) {
    e.preventDefault();
    if (!q.trim()) return;
    setSearching(true);
    try { setHits((await api<{ results: Excerpt[] }>(`/barometers/search?q=${encodeURIComponent(q)}`)).results); }
    catch (ex) { toast.error(ex instanceof ApiError ? ex.message : "Search failed."); }
    finally { setSearching(false); }
  }

  async function remove(d: BarometerDoc) {
    if (!window.confirm(`Remove "${d.title}" and its index? Simulations already run keep the excerpts they used.`)) return;
    try {
      await api(`/barometers/${d.id}`, { method: "DELETE" });
      qc.invalidateQueries({ queryKey: [orgId, "barometers"] });
    } catch (ex) { toast.error(ex instanceof ApiError ? ex.message : "Could not remove it."); }
  }

  const set = (k: keyof typeof blank) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const docs = list.data?.documents ?? [];

  return (
    <Page title="Barometers" subtitle="Public data from countries (statistics, surveys, opinion barometers, reports) that agents draw on. Files are kept exactly as published: agents see them unedited, the way people do.">
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-5">
          <Card className="overflow-hidden">
            <CardHeader title="Library" subtitle={docs.length ? `${docs.length} documents · ${Object.keys(list.data?.countries ?? {}).length} countries` : undefined} divider />
            {list.isLoading ? <div className="space-y-2 p-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-10" />)}</div>
              : list.isError ? <div className="p-4"><Callout tone="neg" title="The library could not be loaded">Refresh the page to try again.</Callout></div>
              : !docs.length ? <Empty icon={<FileText className="h-5 w-5" />} title="No barometer data yet">Add a national statistics table, a survey or a report. Every simulation will draw on the most relevant passages for its countries.</Empty>
              : (
                <div className="overflow-x-auto">
                  <table className="dt">
                    <thead><tr><th>Document</th><th>Country</th><th>Published</th><th>Status</th><th className="!text-right"><span className="sr-only">Actions</span></th></tr></thead>
                    <tbody>{docs.map((d) => (
                      <tr key={d.id}>
                        <td className="max-w-[340px]">
                          <div className="truncate font-medium" title={d.title}>{d.title}</div>
                          <div className="truncate text-2xs text-muted">{d.publisher} · {d.filename} · {fmt.k(d.size)}B{d.scope === "shared" ? " · shared library" : ""}</div>
                          {d.status === "quarantined" && <div className="mt-1 flex gap-1 text-2xs text-neg"><AlertTriangle className="h-3 w-3 shrink-0" aria-hidden />{d.quarantine_reason}</div>}
                        </td>
                        <td>{d.country}</td>
                        <td>{d.published_on ? fmt.day(d.published_on) : "–"}</td>
                        <td>{d.status === "ready" ? <Badge tone="pos">{fmt.n(d.chunk_count)} passages</Badge> : <Badge tone="neg">Quarantined</Badge>}</td>
                        <td className="whitespace-nowrap !text-right">
                          <Button size="sm" variant="ghost" aria-label={`Download the original of ${d.title}`} onClick={() => downloadFile(`/barometers/${d.id}/file`, d.filename).catch((ex) => toast.error(ex.message))}><Download className="h-3.5 w-3.5" /></Button>
                          {(d.scope === "workspace" || isAdmin) && <Button size="sm" variant="ghost" aria-label={`Remove ${d.title}`} onClick={() => remove(d)}><Trash2 className="h-3.5 w-3.5" /></Button>}
                        </td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              )}
          </Card>

          <Card>
            <CardHeader title="Search the library" subtitle="See what agents would read about a topic. Passages are shown exactly as stored, with their source." />
            <form onSubmit={search} className="flex gap-2 px-4 pb-4">
              <Input aria-label="Search barometer passages" value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. unemployment among young people" />
              <Button type="submit" loading={searching}><Search className="h-3.5 w-3.5" />Search</Button>
            </form>
            {hits && (hits.length ? (
              <ul className="space-y-3 border-t border-line p-4">{hits.map((h) => (
                <li key={h.chunk_id} className="rounded-md border border-line p-3">
                  <div className="mb-1 text-2xs text-muted">{h.publisher} · {h.country}{h.published_on ? ` · ${fmt.day(h.published_on)}` : ""} · {h.title} · {h.location}</div>
                  <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed">{h.text}</pre>
                </li>
              ))}</ul>
            ) : <p className="border-t border-line p-4 text-[13px] text-muted">No passages match. Try other words, or add data for that country.</p>)}
          </Card>
        </div>

        <Card className="h-fit">
          <CardHeader title="Add data" subtitle="CSV, TSV, XLSX, JSON, PDF, Word, text, HTML or XML, up to 100 MB. Who published it and where it applies are required, so every passage can be traced." divider />
          <form onSubmit={upload} className="space-y-3 p-4">
            <Field label="File">
              <Input ref={fileRef} type="file" accept={ACCEPT} required onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="h-auto py-1.5 file:mr-3 file:rounded file:border-0 file:bg-raised file:px-2 file:py-0.5 file:text-[12px]" />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Country" hint="AE, FR, US, AE-DU or GLOBAL"><Input required maxLength={8} value={f.country} onChange={set("country")} placeholder="AE" /></Field>
              <Field label="Published on"><Input type="date" value={f.published_on} onChange={set("published_on")} /></Field>
            </div>
            <Field label="Publisher"><Input required maxLength={240} value={f.publisher} onChange={set("publisher")} placeholder="National statistics office" /></Field>
            <Field label="Title" hint="Optional"><Input maxLength={300} value={f.title} onChange={set("title")} placeholder="Uses the file name if empty" /></Field>
            <Field label="Source link" hint="Optional"><Input type="url" maxLength={1000} value={f.source_url} onChange={set("source_url")} placeholder="https://" /></Field>
            {isAdmin && (
              <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={f.shared} onChange={set("shared")} />Add to the shared library (every workspace can read it)</label>
            )}
            <Button type="submit" variant="primary" className="w-full" loading={busy}><Upload className="h-3.5 w-3.5" />Add to library</Button>
            <p className="text-2xs text-muted">Exact duplicates are refused. Files that cannot be read (damaged, scanned images, binary) are kept for review but never shown to agents.</p>
          </form>
        </Card>
      </div>
    </Page>
  );
}
