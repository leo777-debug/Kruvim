import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { Page } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { LineSimple } from "@/components/charts";
import { Card, CardHeader, Empty, KV, Skeleton } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { can, useAuth } from "@/lib/auth";
import type { Asset } from "@/lib/types";
import { fmt } from "@/lib/utils";
import { SimTable } from "../simulations/SimTable";

function bytes(n: number) {
  return n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`;
}

export default function ProjectPage() {
  const { projectId } = useParams();
  const orgId = useAuth((s) => s.orgId);
  const nav = useNavigate();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [batchErrors, setBatchErrors] = useState<{ id: string; error?: string }[]>([]);
  const q = useQuery({ queryKey: [orgId, "project", projectId], queryFn: () => api(`/projects/${projectId}`), refetchInterval: 8000 });
  const p = q.data;
  async function runSelected() {
    setRunning(true);
    try {
      const res = await api<{ results: { id: string; ok: boolean; error?: string }[] }>(`/projects/${projectId}/batch`, { json: { simulation_ids: selected } });
      const failed = res.results.filter((r) => !r.ok);
      setBatchErrors(failed);
      setSelected(failed.map((r) => r.id));
      toast.success(`${res.results.length - failed.length} simulations started`);
      await q.refetch();
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not start batch"); }
    finally { setRunning(false); }
  }
  async function upload(files: FileList | null) {
    for (const f of Array.from(files || [])) {
      const fd = new FormData();
      fd.append("file", f);
      fd.append("kind", "seed");
      try { await api(`/projects/${projectId}/assets`, { method: "POST", body: fd }); toast.success(`${f.name} added`); }
      catch (e) { toast.error(e instanceof ApiError ? e.message : "Upload failed"); }
    }
    qc.invalidateQueries({ queryKey: [orgId, "project", projectId] });
  }
  async function remove(a: Asset) {
    if (!confirm(`Delete ${a.filename}?`)) return;
    await api(`/assets/${a.id}`, { method: "DELETE" });
    qc.invalidateQueries({ queryKey: [orgId, "project", projectId] });
  }
  if (!p) return <div className="p-8"><Skeleton className="h-8 w-60" /></div>;
  const seeds = (p.assets || []).filter((a: Asset) => a.kind === "seed");
  const contentFiles = (p.assets || []).filter((a: Asset) => a.kind !== "seed").length;
  const sims = p.simulations as any[];
  const scored = sims.filter((x) => x.score != null).slice().sort((a, b) => a.created_at.localeCompare(b.created_at));
  const best = scored.reduce((m: any, x: any) => (!m || x.score > m.score ? x : m), null);
  const delta = scored.length > 1 ? scored[scored.length - 1].score - scored[0].score : null;
  return (
    <Page title={p.name} subtitle={p.description} breadcrumb={<Link to="/projects" className="hover:text-fg">Projects</Link>}
      actions={<Button variant="primary" onClick={() => nav(`/projects/${projectId}/new`)}><Plus className="h-4 w-4" />New simulation</Button>}>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card className="overflow-hidden">
          <CardHeader title="Simulations" subtitle={`${sims.length} in this project`} divider actions={can("member") && <Button size="sm" loading={running} disabled={!selected.length || selected.length > 50} onClick={runSelected}>Run selected ({selected.length})</Button>} />
          {batchErrors.length > 0 && <div role="alert" className="p-4 text-sm text-neg">{batchErrors.map((r) => <p key={r.id}>{sims.find((s) => s.id === r.id)?.name || r.id}: {r.error}</p>)}</div>}
          {sims.length === 0 ? <Empty title="No simulations yet" action={<Button variant="primary" onClick={() => nav(`/projects/${projectId}/new`)}>New simulation</Button>}>
            Each simulation tests one piece of content, or an A/B pair, against an audience.</Empty> : <SimTable rows={sims} selected={selected} onSelect={can("member") ? (id, checked) => setSelected((prev) => checked ? [...prev, id] : prev.filter((x) => x !== id)) : undefined} />}
        </Card>
        <div className="space-y-5">
        {scored.length > 1 && (
          <Card className="overflow-hidden">
            <CardHeader title="Opinion over time" divider subtitle="Projected opinion of each completed run in this project, oldest first." />
            <div className="px-4 pt-3"><LineSimple points={scored.map((x, i) => ({ x: i + 1, y: x.score }))} yMax={10} height={140} xFmt={(v) => `#${v}`} yFmt={(v) => v.toFixed(1)} /></div>
            <KV className="px-4 pb-2" rows={[["Change since the first run", <span className={delta! >= 0 ? "text-pos" : "text-neg"}>{delta! >= 0 ? "+" : ""}{delta!.toFixed(2)}</span>],
              ["Best performer", <Link className="text-brand hover:underline" to={`/simulations/${best.id}`}>{best.name} ({best.score.toFixed(2)})</Link>]]} />
          </Card>
        )}
        <Card className="h-fit overflow-hidden">
          <CardHeader title="Background documents" subtitle="Briefs, brand guidelines and research. Added to every simulation's knowledge graph." divider
            actions={<Button size="sm" onClick={() => input.current?.click()}><Upload className="h-3.5 w-3.5" />Upload</Button>} />
          <input ref={input} type="file" multiple className="hidden" accept=".pdf,.md,.txt,.csv,.json" onChange={(e) => upload(e.target.files)} />
          {seeds.length === 0 ? <div className="px-4 py-6 text-[13px] text-muted">No documents. PDF, Markdown, text, CSV and JSON are supported.</div> : (
            <table className="dt">
              <thead><tr><th>File</th><th className="!text-right">Size</th><th className="w-8" /></tr></thead>
              <tbody>{seeds.map((a: Asset) => (
                <tr key={a.id} className="group">
                  <td className="max-w-0 w-full"><div className="truncate font-medium" title={a.filename}>{a.filename}</div><div className="text-xs text-muted">{fmt.day(a.created_at)}</div></td>
                  <td className="r whitespace-nowrap text-muted">{bytes(a.size)}</td>
                  <td><button onClick={() => remove(a)} className="rounded p-1 text-faint hover:bg-raised hover:text-neg" aria-label={`Delete ${a.filename}`}><Trash2 className="h-3.5 w-3.5" /></button></td>
                </tr>
              ))}</tbody>
            </table>
          )}
          {contentFiles > 0 && <div className="border-t border-line px-4 py-2.5 text-xs text-muted">{contentFiles} content file{contentFiles === 1 ? "" : "s"} uploaded through simulations</div>}
        </Card>
        </div>
      </div>
    </Page>
  );
}
