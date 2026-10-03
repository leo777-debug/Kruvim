import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Page } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/overlay";
import { Badge, Card, Empty, Field, Input, Segmented, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useReference } from "@/lib/queries";
import type { Project, SimSummary } from "@/lib/types";
import { fmt, platformName } from "@/lib/utils";

type Run = SimSummary & {project_name: string};
const STATUSES = ["draft", "building_graph", "graph_ready", "preparing", "ready", "queued", "running", "paused", "completed", "failed", "cancelled"];
const REVIEWS = ["none", "in_review", "approved", "changes_requested"];
const label = (value: string) => value.replaceAll("_", " ");

export default function AllRunsPage() {
  const [params, setParams] = useSearchParams();
  const [text, setText] = useState(params.get("q") || "");
  const orgId = useAuth((s) => s.orgId);
  const ref = useReference();
  const projects = useQuery({queryKey:[orgId, "run-projects"], queryFn: () => api<Project[]>("/projects")});
  const [view, setView] = useState<"cards" | "table">("cards");
  const offset = Number(params.get("offset") || 0);
  const q = useQuery({queryKey:[orgId, "all-runs", params.toString()], queryFn: () => api<{items:Run[]; total:number; offset:number; limit:number}>(`/runs?${params}`)});
  function set(key: string, value: string) {
    setParams((previous) => {const next = new URLSearchParams(previous); next.delete("offset"); if (value && value !== "*") next.set(key,value); else next.delete(key); return next;}, {replace:true});
  }
  useEffect(() => {setText(params.get("q") || "");}, [params.get("q")]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (text === (params.get("q") || "")) return;
    const timer = setTimeout(() => set("q", text), 300);
    return () => clearTimeout(timer);
  }, [text, params]); // eslint-disable-line react-hooks/exhaustive-deps
  const select = (key: string, title: string, options: {value:string;label:string}[]) => <Field label={title}><Select value={params.get(key) || "*"} onChange={(v) => set(key,v)} options={[{value:"*",label:`All ${title.toLowerCase()}`},...options]} /></Field>;
  const rows = q.data?.items || [];
  function page(next: number) {setParams((previous) => {const p = new URLSearchParams(previous); p.set("offset", String(next)); return p;});}
  return <Page title="All runs" subtitle="Search and compare every run in your workspace across projects.">
    <Card className="mb-5 p-4"><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Field label="Search runs"><Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Run, project or content title" /></Field>
      {select("project_id","Projects",(projects.data || []).map((p) => ({value:p.id,label:p.name})))}
      {select("format","Formats",(ref.data?.formats || []).map((f) => ({value:f.key,label:f.label})))}
      {select("platform","Platforms",(ref.data?.platforms || []).map((p) => ({value:p.key,label:platformName(p.key)})))}
      {select("status","Statuses",STATUSES.map((s) => ({value:s,label:label(s)})))}
      {select("review_status","Reviewer statuses",REVIEWS.map((s) => ({value:s,label:label(s)})))}
      <Field label="Minimum score"><Input type="number" min={0} max={10} step={.1} value={params.get("score_min") || ""} onChange={(e) => set("score_min", e.target.value)} /></Field>
      <Field label="Maximum score"><Input type="number" min={0} max={10} step={.1} value={params.get("score_max") || ""} onChange={(e) => set("score_max", e.target.value)} /></Field>
      <Field label="From date"><Input type="date" value={params.get("date_from") || ""} onChange={(e) => set("date_from",e.target.value)} /></Field>
      <Field label="Through date"><Input type="date" value={params.get("date_to") || ""} onChange={(e) => set("date_to",e.target.value)} /></Field>
      <Field label="Sort"><Select value={params.get("sort") || "newest"} onChange={(v) => set("sort",v)} options={[{value:"newest",label:"Newest first"},{value:"oldest",label:"Oldest first"},{value:"score_high",label:"Highest score"},{value:"score_low",label:"Lowest score"},{value:"name",label:"Name"}]} /></Field>
      <Button className="self-end" onClick={() => {setText(""); setParams({});}}>Clear filters</Button>
    </div></Card>
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3"><span className="text-sm text-muted">{fmt.n(q.data?.total || 0)} runs</span><Segmented value={view} onChange={setView} options={[{value:"cards",label:"Cards"},{value:"table",label:"Table"}]} /></div>
    {q.error ? <Empty title="Could not load runs">{q.error instanceof Error ? q.error.message : "Please try again."}</Empty> : q.isLoading ? <Skeleton className="h-48" /> : !rows.length ? <Empty title="No runs match">Try widening your filters.</Empty> : view === "cards" ?
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{rows.map((r) => <Link to={`/simulations/${r.id}`} key={r.id} className="card min-w-0 p-4 transition-colors hover:bg-raised">
        <div className="mb-2 flex flex-wrap gap-2"><Badge tone={r.status === "completed" ? "pos" : r.status === "failed" ? "neg" : "outline"}>{label(r.status)}</Badge>{r.dry && <Badge>Dry run</Badge>}</div>
        <h2 className="break-words font-semibold">{r.name}</h2><p className="mt-1 truncate text-xs text-muted">{r.project_name}</p>
        <p className="mt-3 text-xs text-muted">{r.format ? ref.data?.formats.find((f) => f.key === r.format)?.label || label(r.format) : r.content_type} · {platformName(r.platform)}</p>
        <div className="mt-3 flex items-center justify-between text-sm"><span className="num">{r.score != null ? `${fmt.s1(r.score)}/10` : "Unscored"}</span><span className="text-xs text-muted">{fmt.date(r.created_at)}</span></div>
        <p className="mt-2 text-xs text-muted">Review: {label(r.review_status || "none")}</p>
      </Link>)}</div> : <Card className="overflow-x-auto"><table className="dt min-w-[720px]"><thead><tr><th>Run</th><th>Project</th><th>Platform / format</th><th>Status</th><th>Score</th><th>Review</th><th>Created</th></tr></thead><tbody>{rows.map((r) => <tr key={r.id}>
        <td><Link className="font-medium text-brand" to={`/simulations/${r.id}`}>{r.name}</Link></td><td>{r.project_name}</td><td>{platformName(r.platform)} · {label(r.format || r.content_type)}</td><td>{label(r.status)}</td><td>{r.score != null ? fmt.s1(r.score) : "–"}</td><td>{label(r.review_status || "none")}</td><td>{fmt.date(r.created_at)}</td>
      </tr>)}</tbody></table></Card>}
    {q.data && q.data.total > q.data.limit && <div className="mt-4 flex items-center justify-between"><Button disabled={offset === 0} onClick={() => page(Math.max(0,offset-q.data!.limit))}>Previous</Button><span className="text-xs text-muted">{offset + 1}–{Math.min(offset + q.data.limit,q.data.total)} of {q.data.total}</span><Button disabled={offset+q.data.limit >= q.data.total} onClick={() => page(offset+q.data!.limit)}>Next</Button></div>}
  </Page>;
}
