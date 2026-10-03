import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Page } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Field, Input } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { can, useAuth } from "@/lib/auth";
import { useReference } from "@/lib/queries";
import type { Project, SimSummary } from "@/lib/types";
import { fmt } from "@/lib/utils";
import { SimTable } from "../simulations/SimTable";

import { useAlerts } from "./AlertsBell";

interface Watch {
  id: string; name: string; feed_url: string; project_id: string; format: string; platform: string;
  audience: Record<string, unknown>; threshold: number; active: boolean; last_checked_at: string | null; last_error: string | null; runs: number;
}
const selectStyle = "h-8 w-full rounded-md border border-line-strong bg-panel px-2 text-sm";
export default function MonitoringPage() {
  const orgId = useAuth((s) => s.orgId);
  const qc = useQueryClient();
  const ref = useReference();
  const watches = useQuery({ queryKey: [orgId, "watches"], queryFn: () => api<{ limit: number; plan: string; watches: Watch[] }>("/watches"), refetchInterval: 15000 });
  const projects = useQuery({ queryKey: [orgId, "projects"], queryFn: () => api<Project[]>("/projects") });
  const alerts = useAlerts();
  const [busy, setBusy] = useState(false);
  const [runsId, setRunsId] = useState("");
  const [editing, setEditing] = useState<Watch | null>(null);
  const [form, setForm] = useState({ name: "", feed_url: "", project_id: "", format: "social_post", platform: "x", threshold: "0.5", regions: "AE,SA" });
  const runs = useQuery({ queryKey: [orgId, "watch-runs", runsId], queryFn: () => api<SimSummary[]>(`/watches/${runsId}/runs`), enabled: !!runsId, refetchInterval: 8000 });
  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }));
  async function act(work: () => Promise<unknown>) {
    setBusy(true);
    try { await work(); await Promise.all([qc.invalidateQueries({ queryKey: [orgId, "watches"] }), qc.invalidateQueries({ queryKey: [orgId, "alerts"] }), qc.invalidateQueries({ queryKey: [orgId, "watch-runs"] })]); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not update monitoring"); }
    finally { setBusy(false); }
  }
  function edit(w: Watch) {
    setEditing(w);
    setForm({ name: w.name, feed_url: w.feed_url, project_id: w.project_id, format: w.format, platform: w.platform, threshold: String(w.threshold), regions: ((w.audience.regions as string[]) || []).join(",") });
  }
  const error = watches.error || projects.error || alerts.error;
  return <Page title="Monitoring" subtitle="Test new competitor posts from public RSS or Atom feeds and follow changes in your audience. Feeds are checked hourly; normal simulation limits and credits apply.">
    {error && <div role="alert" className="mb-4 text-neg">{error.message}</div>}
    <div className="grid gap-5 xl:grid-cols-2">
      <Card><CardHeader title="Competitor feeds" subtitle={watches.data ? `${watches.data.watches.length} of ${watches.data.limit} feeds · ${watches.data.plan} plan` : "Loading feeds…"} divider />
        <div className="space-y-4 p-4">
          {watches.data?.watches.length === 0 && <p className="text-sm text-muted">No feeds yet. Add a public competitor feed to start monitoring.</p>}
          {watches.data?.watches.map((w) => <section key={w.id} className="space-y-2 rounded border border-line p-3">
            <h2 className="font-medium">{w.name} <span className="text-xs text-muted">{w.active ? "Active" : "Paused"}</span></h2>
            <p className="break-all text-xs text-muted">{w.feed_url}</p>
            <p className="text-xs text-muted">{w.runs} runs · Last checked {w.last_checked_at ? fmt.ago(w.last_checked_at) : "never"} · Alert when {w.threshold} points above your average</p>
            {w.last_error && <p role="alert" className="text-sm text-neg">{w.last_error}</p>}
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => setRunsId(w.id)}>View runs</Button>
              {can("member") && <Button size="sm" disabled={busy} onClick={() => act(async () => { const r = await api<{ new: number; error?: string }>(`/watches/${w.id}/check`, { method: "POST" }); if (r.error) toast.error(r.error); else toast.success(`${r.new} new posts queued`); })}>Check now</Button>}
              {can("admin") && <><Button size="sm" disabled={busy} onClick={() => edit(w)}>Edit</Button><Button size="sm" disabled={busy} onClick={() => act(() => api(`/watches/${w.id}`, { method: "PATCH", json: { ...w, active: !w.active } }))}>{w.active ? "Pause" : "Resume"}</Button><Button size="sm" variant="danger" disabled={busy} onClick={() => { if (confirm(`Delete feed ${w.name}?`)) void act(() => api(`/watches/${w.id}`, { method: "DELETE" })); }}>Delete</Button></>}
            </div>
          </section>)}
        </div>
      </Card>
      {can("admin") && <Card><CardHeader title={editing ? "Edit feed" : "Add competitor feed"} divider />
        <form className="space-y-3 p-4" onSubmit={(e) => { e.preventDefault(); void act(async () => {
          await api(editing ? `/watches/${editing.id}` : "/watches", { method: editing ? "PATCH" : "POST", json: { name: form.name.trim(), feed_url: form.feed_url.trim(), project_id: form.project_id, format: form.format, platform: form.platform, threshold: Number(form.threshold), active: editing?.active ?? true, audience: { ...(editing?.audience || {}), regions: form.regions.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean) } } });
          setEditing(null); setForm((f) => ({ ...f, name: "", feed_url: "" })); toast.success("Feed saved");
        }); }}>
          <Field label="Competitor name"><Input aria-label="Competitor name" required maxLength={200} value={form.name} onChange={(e) => set("name", e.target.value)} /></Field>
          <Field label="Public feed URL"><Input aria-label="Public feed URL" required type="url" maxLength={1000} value={form.feed_url} onChange={(e) => set("feed_url", e.target.value)} placeholder="https://example.com/feed.xml" /></Field>
          <Field label="Project"><select aria-label="Project" required className={selectStyle} value={form.project_id} onChange={(e) => set("project_id", e.target.value)}><option value="">Choose project</option>{projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
          <Field label="Content format"><select aria-label="Content format" className={selectStyle} value={form.format} onChange={(e) => set("format", e.target.value)}>{ref.data?.formats.filter((f) => f.type === "text" && !f.poll).map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}</select></Field>
          <Field label="Platform"><select aria-label="Platform" className={selectStyle} value={form.platform} onChange={(e) => set("platform", e.target.value)}>{ref.data?.platforms.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}</select></Field>
          <Field label="Audience regions" help="Comma-separated country codes, for example AE, SA. Leave blank for all regions."><Input aria-label="Audience regions" value={form.regions} onChange={(e) => set("regions", e.target.value)} /></Field>
          <Field label="Alert threshold" help="Points above your average opinion score, from 0 to 5."><Input aria-label="Alert threshold" required type="number" min={0} max={5} step={0.1} value={form.threshold} onChange={(e) => set("threshold", e.target.value)} /></Field>
          <div className="flex gap-2"><Button type="submit" variant="primary" loading={busy} disabled={!editing && !!watches.data && watches.data.watches.length >= watches.data.limit}>{editing ? "Save feed" : "Add feed"}</Button>{editing && <Button type="button" onClick={() => { setEditing(null); setForm((f) => ({ ...f, name: "", feed_url: "" })); }}>Cancel edit</Button>}</div>
          {watches.data?.limit === 0 && <p className="text-sm text-muted">Competitor monitoring requires Pro or above.</p>}
        </form>
      </Card>}
    </div>
    {runsId && <Card className="mt-5"><CardHeader title="Feed runs" divider />{runs.error ? <p role="alert" className="p-4 text-neg">{runs.error.message}</p> : runs.data?.length ? <SimTable rows={runs.data} /> : <p className="p-4 text-sm text-muted">{runs.isLoading ? "Loading runs…" : "No runs for this feed yet."}</p>}</Card>}
    <Card id="alerts" className="mt-5"><CardHeader title={`Alerts (${alerts.data?.unread || 0} unread)`} divider actions={<Button size="sm" disabled={busy || !alerts.data?.unread} onClick={() => act(() => api("/alerts/read", { json: {} }))}>Mark all read</Button>} />
      <div className="divide-y divide-line">{alerts.data?.items.map((a) => <article key={a.id} className={`p-4 ${a.read ? "" : "bg-brand-soft/30"}`}><div className="flex flex-wrap justify-between gap-2"><h2 className="font-medium">{a.title}</h2><span className="text-xs text-muted">{fmt.ago(a.created_at)}</span></div><p className="mt-1 text-sm text-muted">{a.body}</p><div className="mt-2 flex gap-3">{a.simulation_id && <Link to={`/simulations/${a.simulation_id}`} className="text-sm text-brand">View simulation</Link>}{!a.read && <Button size="sm" disabled={busy} onClick={() => act(() => api("/alerts/read", { json: { ids: [a.id] } }))}>Mark read</Button>}</div></article>)}</div>
      {alerts.data?.items.length === 0 && <p className="p-4 text-sm text-muted">No alerts yet. Competitor results, significant weekly changes and failed automatic runs appear here.</p>}
    </Card>
  </Page>;
}
