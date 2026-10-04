import { useMutation, useQuery } from "@tanstack/react-query";
import { ExternalLink, Search, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Page } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Dialog, Select } from "@/components/ui/overlay";
import { Callout, Card, CardHeader, CheckRow, Empty, Field, Input, KV, Skeleton, Status, Switch, UnderlineTabs } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { REGION_COLORS } from "@/lib/colors";
import { useReference } from "@/lib/queries";
import { fmt, platformName } from "@/lib/utils";

export default function DataPoolPage() {
  const [tab, setTab] = useState("world");
  return (
    <Page wide title="Data pool" subtitle="Live inputs every simulation is conditioned on: weather, news, news tone, attention, holidays, economy and social platforms. Fetched on a schedule and archived hourly so any past moment can be replayed. Survey data calibrates the population itself.">
      <UnderlineTabs value={tab} onChange={setTab} className="mb-5" tabs={[
        { key: "world", label: "Regions" }, { key: "signals", label: "Signals" }, { key: "connectors", label: "Connectors" },
        { key: "listen", label: "Social listening" }, { key: "barometers", label: "Survey data" },
      ]} />
      {tab === "world" && <World />}
      {tab === "signals" && <Signals />}
      {tab === "connectors" && <Connectors />}
      {tab === "listen" && <Listen />}
      {tab === "barometers" && <Barometers />}
    </Page>
  );
}

function World() {
  const q = useQuery({ queryKey: ["world", "all"], queryFn: () => api("/datapool/world"), staleTime: 120_000 });
  if (q.isLoading) return <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">{[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-72" />)}</div>;
  return (
    <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
      {Object.values(q.data || {}).map((w: any) => (
        <Card key={w.region} className="flex flex-col overflow-hidden">
          <div className="flex items-start justify-between border-b border-line px-4 py-3">
            <div>
              <div className="flex items-center gap-2 text-[14px] font-semibold"><span className="h-2.5 w-2.5 rounded-[2px]" style={{ background: REGION_COLORS[w.region] }} />{w.city}</div>
              <div className="text-xs text-muted">{w.name} · {w.local_time} local time</div>
            </div>
            {w.weather && <div className="text-right"><div className="num text-xl font-semibold">{Math.round(w.weather.temp_c)}°C</div><div className="text-xs text-muted">{w.weather.text}</div></div>}
          </div>
          <div className="flex-1 px-4 py-3">
            <p dir="auto" className="text-[13px] leading-relaxed">{w.brief}</p>
            <div className="mt-1 text-[11px] text-faint">{w.brief_by === "template" ? "Automatic summary. Connect a model for written briefs." : `Summary by ${w.brief_by}`}</div>
            <KV className="mt-3" rows={[
              ["News tone", w.tone?.avg != null ? `${w.tone.avg > 0 ? "+" : ""}${w.tone.avg.toFixed(1)}` : "Source unavailable"],
              ["Upcoming", w.events?.length ? w.events.slice(0, 2).map((e: any) => e.days_away == null ? e.name : `${e.name} (${e.days_away} d)`).join(", ") : "Source unavailable"],
              ["Economy", w.economy?.[0]?.title || "–"],
            ]} />
            {w.tone && <p className="mt-1 text-[11px] text-muted">{w.tone.source_label || "GDELT"}</p>}
            <div className="mt-4 text-xs font-medium text-muted">Headlines</div>
            <ul className="mt-1 space-y-1 text-[13px]">{(w.news || []).slice(0, 4).map((n: any, i: number) => <li key={i} dir="auto" className="line-clamp-1">{n.title} <span className="text-faint">· {n.source}</span></li>)}</ul>
            {w.trending?.length > 0 && <><div className="mt-3 text-xs font-medium text-muted">Most read</div>
              <div dir="auto" className="mt-1 text-[13px] text-muted">{w.trending.slice(0, 5).map((t: any) => t.title).join(" · ")}</div></>}
            {w.social?.length > 0 && <><div className="mt-3 text-xs font-medium text-muted">Social trends</div>
              <div className="mt-1 text-[13px] text-muted">{w.social.slice(0, 6).map((t: any) => t.title).join(" · ")}</div></>}
          </div>
        </Card>
      ))}
    </div>
  );
}

function Signals() {
  const ref = useReference();
  const [f, setF] = useState({ region: "", kind: "", source: "", hours: 24 });
  const q = useQuery({ queryKey: ["signals", f], queryFn: () => api<any[]>(`/datapool/signals?${new URLSearchParams(Object.entries(f).filter(([, v]) => v).map(([k, v]) => [k, String(v)]))}&limit=300`) });
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-end gap-3 border-b border-line p-3">
        <Field label="Region" className="w-40"><Select value={f.region || "*"} onChange={(v) => setF({ ...f, region: v === "*" ? "" : v })} options={[{ value: "*", label: "All" }, ...(ref.data?.regions || []).map((r) => ({ value: r.code, label: r.name }))]} /></Field>
        <Field label="Type" className="w-40"><Select value={f.kind || "*"} onChange={(v) => setF({ ...f, kind: v === "*" ? "" : v })} options={["*", "weather", "headline", "tone", "trend", "event", "economy", "social_trend", "social_post"].map((k) => ({ value: k, label: k === "*" ? "All" : k.replace("_", " ") }))} /></Field>
        <Field label="Source" className="w-44"><Select value={f.source || "*"} onChange={(v) => setF({ ...f, source: v === "*" ? "" : v })} options={[{ value: "*", label: "All" }, ...(ref.data?.connectors || []).map((c) => ({ value: c.key, label: c.name }))]} /></Field>
        <Field label="Window" className="w-32"><Select value={String(f.hours)} onChange={(v) => setF({ ...f, hours: Number(v) })} options={[6, 24, 72, 168, 720].map((h) => ({ value: String(h), label: h < 48 ? `${h} hours` : `${h / 24} days` }))} /></Field>
        <span className="num ml-auto text-xs text-muted">{fmt.n(q.data?.length)} signals</span>
      </div>
      <div className="max-h-[640px] overflow-auto">
        <table className="dt min-w-[860px]">
          <thead><tr><th>Fetched</th><th>Source</th><th>Type</th><th>Region</th><th>Signal</th><th className="!text-right">Value</th></tr></thead>
          <tbody>{(q.data || []).map((s) => (
            <tr key={s.id}>
              <td className="num whitespace-nowrap text-muted">{fmt.ago(s.fetched_at)}</td><td className="whitespace-nowrap">{s.source.replace(/_/g, " ")}</td>
              <td className="whitespace-nowrap capitalize text-muted">{s.kind.replace("_", " ")}</td>
              <td className="whitespace-nowrap"><span className="mr-1.5 inline-block h-2 w-2 rounded-[2px]" style={{ background: REGION_COLORS[s.region] || "#9aa1ac" }} />{s.region}</td>
              <td dir="auto" className="max-w-0 w-full"><span className="block truncate">{s.title}</span></td>
              <td className="r whitespace-nowrap">{s.value != null ? fmt.k(s.value) : ""}{s.url && <a href={s.url} target="_blank" rel="noreferrer" className="ml-2 inline-block text-muted hover:text-fg" aria-label="Open source"><ExternalLink className="h-3 w-3" /></a>}</td>
            </tr>))}</tbody>
        </table>
      </div>
    </Card>
  );
}

const CATEGORY_LABEL: Record<string, string> = { weather: "Weather", news: "News", tone: "News tone", attention: "Attention", events: "Calendar", economy: "Economy", social: "Social" };

function Connectors() {
  const user = useAuth((s) => s.user);
  const q = useQuery({ queryKey: ["connectors"], queryFn: () => api<any[]>("/datapool/connectors"), refetchInterval: 15000 });
  const [edit, setEdit] = useState<any>(null);
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: (body: any) => api(`/datapool/connectors/${edit?.key ?? body.key}`, { method: "PATCH", json: body }),
    onSuccess: () => { q.refetch(); setEdit(null); toast.success("Connector updated"); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });
  const run = useMutation({ mutationFn: (k: string) => api(`/datapool/connectors/${k}/run`, { method: "POST" }), onSuccess: () => toast.success("Run queued"),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed") });
  const order = Object.keys(CATEGORY_LABEL);
  const rows = (q.data || []).slice().sort((a, b) => order.indexOf(a.category) - order.indexOf(b.category) || a.name.localeCompare(b.name));
  return (
    <div className="space-y-4">
      {!user?.is_superuser && <Callout tone="info">Shared connectors are managed by platform administrators. You can add your organisation's own social credentials for live listening; they are encrypted and used only for your simulations.</Callout>}
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="dt min-w-[980px]">
            <thead><tr>{user?.is_superuser && <th className="w-12">On</th>}<th>Connector</th><th>Category</th><th>Status</th><th>Schedule</th><th className="!text-right">Last run</th><th className="!text-right">Items (last / total)</th><th className="w-48" /></tr></thead>
            <tbody>{rows.map((c) => {
              const needs = c.secrets.length > 0;
              const hasCreds = c.secrets.every((s: string) => c.credentials[s]);
              return (
                <tr key={c.key}>
                  {user?.is_superuser && <td><Switch checked={c.enabled} onChange={(v) => save.mutate({ key: c.key, enabled: v, scope: "platform" })} /></td>}
                  <td className="max-w-[340px]">
                    <div className="font-medium">{c.name}</div>
                    <div className="line-clamp-1 text-xs text-muted" title={c.description}>{c.description}</div>
                    {c.last_error && <div className="line-clamp-1 text-xs text-neg" title={c.last_error}>{c.last_error}</div>}
                  </td>
                  <td className="text-muted">{CATEGORY_LABEL[c.category] || c.category}</td>
                  <td>{c.last_status === "ok" ? <Status tone="pos">Healthy</Status> : c.last_status === "error" ? <Status tone="neg">Error</Status>
                    : c.last_status === "skipped" ? <Status tone="warn">Needs credentials</Status> : <Status>Not run</Status>}
                    <div className="mt-0.5 text-xs text-muted">{needs ? (hasCreds ? "Credentials set" : "Credentials required") : "No key needed"}{c.supports_search ? " · listening" : ""}</div></td>
                  <td className="whitespace-nowrap text-muted">{c.interval_minutes > 0 ? `Every ${c.interval_minutes >= 60 ? `${c.interval_minutes / 60} h` : `${c.interval_minutes} min`}` : "On demand"}</td>
                  <td className="r whitespace-nowrap text-muted">{fmt.ago(c.last_run_at)}
                    <div className={c.freshness?.stale ? "text-xs text-neg" : "text-xs text-muted"}>{c.freshness?.age_hours == null ? "No fresh data" : `${c.freshness.age_hours} h old · ${c.freshness.stale ? "stale" : "within limit"}`}</div></td>
                  <td className="r whitespace-nowrap">{fmt.n(c.last_items)} / {fmt.n(c.total_items)}</td>
                  <td>
                    <div className="flex items-center justify-end gap-1.5">
                      {needs && <Button size="sm" onClick={() => { setEdit(c); setSecrets({}); }}>{hasCreds ? "Update keys" : "Add keys"}</Button>}
                      {user?.is_superuser && c.interval_minutes > 0 && <Button size="sm" onClick={() => run.mutate(c.key)}>Run now</Button>}
                      {c.docs_url && <a href={c.docs_url} target="_blank" rel="noreferrer" className="text-xs text-brand hover:underline">Docs</a>}
                    </div>
                  </td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      </Card>
      <Dialog open={!!edit} onOpenChange={(v) => !v && setEdit(null)} title={`${edit?.name} credentials`} description="Stored encrypted. Leave a field blank to keep its current value."
        footer={<><Button onClick={() => setEdit(null)}>Cancel</Button><Button variant="primary" loading={save.isPending}
          onClick={() => save.mutate({ secrets, scope: user?.is_superuser ? "platform" : "org" })}>Save</Button></>}>
        <div className="space-y-3">
          {edit?.license_note && <p className="text-xs text-muted">{edit.license_note}</p>}
          {edit?.secrets.map((s: string) => (
            <Field key={s} label={s.replace(/_/g, " ")} hint={edit.credentials[s] ? "Currently set" : undefined}>
              <Input type="password" autoComplete="off" value={secrets[s] || ""} onChange={(e) => setSecrets({ ...secrets, [s]: e.target.value })} />
            </Field>
          ))}
        </div>
      </Dialog>
    </div>
  );
}

function Listen() {
  const ref = useReference();
  const [qtext, setQ] = useState("");
  const [regions, setRegions] = useState<string[]>(["AE"]);
  const m = useMutation({ mutationFn: () => api<any[]>("/datapool/listen", { json: { query: qtext, regions } }), onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed") });
  return (
    <div className="grid gap-5 lg:grid-cols-[340px_1fr]">
      <Card className="h-fit space-y-4 p-4">
        <div>
          <div className="section-title">Search live conversation</div>
          <p className="mt-1 text-xs leading-relaxed text-muted">Queries every social connector with search: Mastodon, Bluesky, Reddit, YouTube, X and Google News, depending on configured keys. Simulations are seeded the same way.</p>
        </div>
        <Field label="Topic"><Input value={qtext} onChange={(e) => setQ(e.target.value)} placeholder="ramadan fitness" onKeyDown={(e) => e.key === "Enter" && m.mutate()} /></Field>
        <Field label="Regions">
          <div className="grid grid-cols-2 rounded-md border border-line p-1">
            {(ref.data?.regions || []).map((r) => <CheckRow key={r.code} checked={regions.includes(r.code)} onChange={() => setRegions(regions.includes(r.code) ? regions.filter((x) => x !== r.code) : [...regions, r.code])} label={r.short} />)}
          </div>
        </Field>
        <Button variant="primary" className="w-full" disabled={qtext.trim().length < 2} loading={m.isPending} onClick={() => m.mutate()}><Search className="h-4 w-4" />Search</Button>
      </Card>
      <Card className="overflow-hidden">
        {!m.data ? <Empty title="No search yet">Enter a topic to see what people are posting about it now.</Empty> : m.data.length === 0 ? <Empty title="Nothing found">Try a broader term, or add Reddit, YouTube, X or Bluesky keys under Connectors.</Empty> : (
          <>
            <div className="border-b border-line bg-raised px-4 py-2 text-xs text-muted">{m.data.length} posts</div>
            <div className="divide-y divide-line">
              {m.data.map((p, i) => (
                <div key={i} className="px-4 py-3">
                  <div className="flex items-center gap-1.5 text-xs text-muted"><span className="font-medium text-fg">{platformName(p.platform)}</span>· @{p.author} · {fmt.ago(p.observed_at)}
                    <span className="num ml-auto">{fmt.n(p.engagement)} engagements</span>{p.url && <a href={p.url} target="_blank" rel="noreferrer" aria-label="Open post" className="hover:text-fg"><ExternalLink className="h-3 w-3" /></a>}</div>
                  <div dir="auto" className="mt-1 text-[13px] leading-relaxed">{p.text}</div>
                </div>
              ))}
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

function Barometers() {
  const user = useAuth((s) => s.user);
  const list = useQuery({ queryKey: ["datasets"], queryFn: () => api<any[]>("/datapool/datasets") });
  const pop = useQuery({ queryKey: ["population"], queryFn: () => api("/datapool/population"), refetchInterval: 8000 });
  const input = useRef<HTMLInputElement>(null);
  const [mapFor, setMapFor] = useState<any>(null);
  async function upload(file: File) {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("name", file.name.replace(/\.csv$/i, ""));
    fd.append("source", /arab/i.test(file.name) ? "arab_barometer" : /wvs|values/i.test(file.name) ? "wvs" : /pew/i.test(file.name) ? "pew" : "custom");
    try {
      const d = await api("/datapool/datasets", { method: "POST", body: fd });
      await list.refetch();
      setMapFor({ ...d, name: file.name });
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Upload failed"); }
  }
  async function apply(id: string) {
    try {
      const r = await api(`/datapool/datasets/${id}/apply`, { method: "POST" });
      toast.success(`Rebuilding the population with priors for ${r.regions.join(", ")}`);
      list.refetch(); pop.refetch();
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
  }
  const dsTone = (s: string) => (s === "applied" ? "pos" : s === "mapped" ? "brand" : s === "error" ? "neg" : "default") as any;
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="space-y-4">
        <Callout tone="info" title="Calibrate the population with survey microdata">
          Upload respondent-level CSV files from Arab Barometer, Pew Global Attitudes, the World Values Survey or census microdata. Map the columns once;
          Kruvim computes weighted age, sex, education and attitude marginals per country and rebuilds the 1,000,000-agent population from them.
        </Callout>
        <Card className="overflow-hidden">
          <CardHeader title="Datasets" divider actions={<Button size="sm" variant="primary" onClick={() => input.current?.click()}><Upload className="h-3.5 w-3.5" />Upload CSV</Button>} />
          <input ref={input} type="file" accept=".csv,.tsv,.txt" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          {(list.data || []).length === 0 ? <Empty title="No datasets yet">Upload a CSV to start.</Empty> : (
            <div className="overflow-x-auto">
              <table className="dt min-w-[720px]">
                <thead><tr><th>Dataset</th><th>Countries</th><th className="!text-right">Rows</th><th>Status</th><th className="w-44" /></tr></thead>
                <tbody>{list.data!.map((d) => (
                  <tr key={d.id}>
                    <td><div className="font-medium">{d.name}</div><div className="text-xs text-muted">{d.source.replace("_", " ")} · {d.columns.length} columns · {fmt.day(d.created_at)}</div></td>
                    <td className="text-xs text-muted">{d.summary?.regions ? Object.entries(d.summary.regions).map(([k, v]: any) => `${k} (${fmt.n(v.respondents)})`).join(", ") : "–"}</td>
                    <td className="r">{fmt.n(d.rows)}</td>
                    <td><Status tone={dsTone(d.status)}><span className="capitalize">{d.status}</span></Status></td>
                    <td><div className="flex justify-end gap-1.5">
                      <Button size="sm" onClick={() => setMapFor(d)}>Map columns</Button>
                      {user?.is_superuser && d.status !== "uploaded" && <Button size="sm" variant="primary" onClick={() => apply(d.id)}>Apply</Button>}
                    </div></td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
      <Card className="h-fit overflow-hidden">
        <CardHeader title="Population versions" subtitle={`Active: ${pop.data?.active?.label ?? "…"}`} divider />
        <table className="dt">
          <thead><tr><th>Version</th><th>Status</th></tr></thead>
          <tbody>{(pop.data?.versions || []).map((v: any) => (
            <tr key={v.id}>
              <td><div className="font-medium">{v.label}</div><div className="text-xs text-muted">{fmt.date(v.created_at)}{v.regions?.length ? ` · ${v.regions.join(", ")}` : ""}</div>
                {v.error && <div className="text-xs text-neg">{v.error}</div>}</td>
              <td className="whitespace-nowrap"><Status tone={v.is_active ? "pos" : v.status === "error" ? "neg" : v.status === "building" ? "warn" : "default"}>{v.is_active ? "Active" : <span className="capitalize">{v.status}</span>}</Status></td>
            </tr>
          ))}</tbody>
        </table>
      </Card>
      {mapFor && <MappingDialog d={mapFor} onClose={() => { setMapFor(null); list.refetch(); }} />}
    </div>
  );
}

function MappingDialog({ d, onClose }: { d: any; onClose: () => void }) {
  const cols = d.columns as string[];
  const guess = (re: RegExp) => cols.find((c) => re.test(c)) || "";
  const [m, setM] = useState<any>(d.mapping?.country_col ? d.mapping : {
    country_col: guess(/country|cntry|nation|^q?1$/i), weight_col: guess(/^w(ei)?gh?t|^wt/i), age_col: guess(/^age|q1001/i), sex_col: guess(/sex|gender|q1002/i),
    male_values: ["1", "male", "m"], education_col: guess(/edu/i), education_map: {}, attitudes: {},
  });
  const [summary, setSummary] = useState<any>(d.summary?.regions ? d.summary : null);
  const run = useMutation({ mutationFn: () => api(`/datapool/datasets/${d.id}/mapping`, { method: "PUT", json: m }), onSuccess: (r) => setSummary(r.summary),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed") });
  const opt = [{ value: "-", label: "None" }, ...cols.map((c) => ({ value: c, label: c }))];
  const set = (k: string) => (v: string) => setM({ ...m, [k]: v === "-" ? "" : v });
  const att = (name: string, key: string, v: any) => setM({ ...m, attitudes: { ...m.attitudes, [name]: { min: 1, max: 4, ...(m.attitudes[name] || {}), [key]: v } } });
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()} wide title={`Map columns: ${d.name}`} description="Countries are recognised by name or ISO code; other countries are ignored."
      footer={<><Button onClick={onClose}>Close</Button><Button variant="primary" loading={run.isPending} onClick={() => run.mutate()}>Compute marginals</Button></>}>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Country column"><Select value={m.country_col || "-"} onChange={set("country_col")} options={opt} /></Field>
        <Field label="Weight column"><Select value={m.weight_col || "-"} onChange={set("weight_col")} options={opt} /></Field>
        <Field label="Age column"><Select value={m.age_col || "-"} onChange={set("age_col")} options={opt} /></Field>
        <Field label="Sex column"><Select value={m.sex_col || "-"} onChange={set("sex_col")} options={opt} /></Field>
        <Field label="Values meaning male" hint="Comma separated"><Input value={(m.male_values || []).join(",")} onChange={(e) => setM({ ...m, male_values: e.target.value.split(",").map((x) => x.trim()) })} /></Field>
        <Field label="Education column"><Select value={m.education_col || "-"} onChange={set("education_col")} options={opt} /></Field>
      </div>
      {m.education_col && (
        <Field className="mt-3" label="Education codes to level" help='0 secondary or less, 1 diploma, 2 bachelor’s, 3 postgraduate. Example: {"1":0,"2":0,"3":1,"4":2,"5":3}'>
          <Input className="mono" value={JSON.stringify(m.education_map || {})} onChange={(e) => { try { setM({ ...m, education_map: JSON.parse(e.target.value) }); } catch { /* typing */ } }} />
        </Field>
      )}
      <div className="mb-2 mt-5 text-[13px] font-medium">Attitudes (scaled to 0–1)</div>
      <div className="overflow-hidden rounded-md border border-line">
        <table className="dt">
          <thead><tr><th>Attitude</th><th>Column</th><th className="w-20">Min</th><th className="w-20">Max</th><th className="w-28">Reverse</th></tr></thead>
          <tbody>{["religiosity", "media_trust", "political_interest"].map((a) => (
            <tr key={a}>
              <td className="capitalize">{a.replace("_", " ")}</td>
              <td><Select value={m.attitudes?.[a]?.col || "-"} onChange={(v) => att(a, "col", v === "-" ? "" : v)} options={opt} /></td>
              <td><Input type="number" value={m.attitudes?.[a]?.min ?? 1} onChange={(e) => att(a, "min", Number(e.target.value))} aria-label="Minimum" /></td>
              <td><Input type="number" value={m.attitudes?.[a]?.max ?? 4} onChange={(e) => att(a, "max", Number(e.target.value))} aria-label="Maximum" /></td>
              <td><Switch checked={!!m.attitudes?.[a]?.reverse} onChange={(v) => att(a, "reverse", v)} /></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <div className="mb-2 mt-5 text-[13px] font-medium">Preview</div>
      <div className="overflow-x-auto rounded-md border border-line">
        <table className="dt"><thead><tr>{cols.slice(0, 12).map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>{(d.preview || []).slice(0, 4).map((r: string[], i: number) => <tr key={i}>{r.slice(0, 12).map((v, j) => <td key={j} className="text-xs">{v}</td>)}</tr>)}</tbody></table>
      </div>
      {summary && (
        <>
          <div className="mb-2 mt-5 text-[13px] font-medium">Computed marginals</div>
          <div className="overflow-x-auto rounded-md border border-line">
            <table className="dt">
              <thead><tr><th>Country</th><th className="!text-right">Respondents</th><th className="!text-right">Male</th><th>Age bands</th><th>Education</th><th>Attitudes</th></tr></thead>
              <tbody>{Object.entries(summary.regions).map(([k, v]: any) => (
                <tr key={k}>
                  <td className="font-medium">{k}</td><td className="r">{fmt.n(v.respondents)}</td><td className="r">{v.male_share != null ? fmt.pct(v.male_share) : "–"}</td>
                  <td className="num text-xs">{v.age_bands ? v.age_bands.map((x: number) => fmt.pct(x)).join(" / ") : "–"}</td>
                  <td className="num text-xs">{v.education ? v.education.map((x: number) => fmt.pct(x)).join(" / ") : "–"}</td>
                  <td className="num text-xs">{v.attitudes ? Object.entries(v.attitudes).map(([a, x]: any) => `${a.replace("_", " ")} ${x.toFixed(2)}`).join(", ") : "–"}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          {Object.keys(summary.unmatched_countries || {}).length > 0 && <div className="mt-2 text-xs text-muted">Ignored countries: {Object.keys(summary.unmatched_countries).join(", ")}</div>}
        </>
      )}
    </Dialog>
  );
}
