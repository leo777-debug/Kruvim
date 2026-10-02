import { useQuery } from "@tanstack/react-query";
import { Check, FolderPlus, Plus } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { LineSimple } from "@/components/charts";
import { Page } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Callout, Card, CardHeader, Empty, Skeleton, Stat } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { REGION_COLORS } from "@/lib/colors";
import type { SimSummary } from "@/lib/types";
import { fmt } from "@/lib/utils";
import { SimTable } from "../simulations/SimTable";

export default function DashboardPage() {
  const orgId = useAuth((s) => s.orgId);
  const nav = useNavigate();
  const sims = useQuery({ queryKey: [orgId, "sims"], queryFn: () => api<SimSummary[]>("/simulations?limit=50"), refetchInterval: 10000 });
  const usage = useQuery({ queryKey: [orgId, "usage"], queryFn: () => api("/usage") });
  const world = useQuery({ queryKey: ["world", "MENA"], queryFn: () => api("/datapool/world?regions=AE,SA,EG,JO,MA,US"), staleTime: 300_000 });
  const pool = useQuery({ queryKey: ["pool-stats"], queryFn: () => api("/datapool/stats"), staleTime: 60_000 });
  const providers = useQuery({ queryKey: [orgId, "providers"], queryFn: () => api("/providers") });
  const list = sims.data || [];
  const done = list.filter((s) => s.score != null);
  const running = list.filter((s) => ["running", "queued", "paused", "building_graph", "preparing"].includes(s.status)).length;
  const trend = done.slice().reverse().map((s, i) => ({ x: i + 1, y: s.score! }));
  const dry = providers.data?.active?.provider === "dryrun";
  const projects = useQuery({ queryKey: [orgId, "projects"], queryFn: () => api<any[]>("/projects") });
  const reviewed = list.some((s) => s.report_status === "done");
  const steps = [
    { done: !dry, title: "Connect a language model", text: "Optional. Without one, everything runs as a dry run so you can explore.", to: "/settings?tab=provider", cta: "Connect" },
    { done: (projects.data || []).length > 0, title: "Create a project", text: "A project groups simulations for one campaign, client or channel.", to: "/projects?new=1", cta: "Create" },
    { done: list.length > 0, title: "Test a piece of content", text: "Upload a reel, podcast, thumbnail, post or poll and pick an audience.", to: "/projects", cta: "Start" },
    { done: reviewed, title: "Read the results", text: "See what happened, what to change and how it ranks, then interview any agent.", to: list[0] ? `/simulations/${list[0].id}` : "/projects", cta: "Open" },
  ];
  const showSetup = !sims.isLoading && steps.some((s) => !s.done) && list.length < 3;
  const sources = Object.entries(pool.data?.last_24h?.by_source || {}).sort((a: any, b: any) => b[1] - a[1]) as [string, number][];

  return (
    <Page title="Overview" subtitle="Simulations, live data coverage and credit usage for this workspace."
      actions={<><Button onClick={() => nav("/projects?new=1")}><FolderPlus className="h-4 w-4" />New project</Button>
        <Button variant="primary" onClick={() => nav("/projects")}><Plus className="h-4 w-4" />New simulation</Button></>}>
      {dry && (
        <Callout tone="warn" className="mb-5" title="No language model connected"
          action={<Button size="sm" onClick={() => nav("/settings?tab=provider")}>Connect a model</Button>}>
          Simulations run in dry-run mode: reactions come from the statistical model only. Connect a cloud API key or a local model for agent-written reactions.
        </Callout>
      )}
      {showSetup && (
        <Card className="mb-5 overflow-hidden">
          <CardHeader title="Getting started" subtitle={`${steps.filter((s) => s.done).length} of ${steps.length} done`} divider />
          <ol className="grid divide-y divide-line md:grid-cols-4 md:divide-x md:divide-y-0">
            {steps.map((s, i) => (
              <li key={s.title} className="flex flex-col gap-1.5 p-4">
                <div className="flex items-center gap-2">
                  <span className={`num flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-semibold ${s.done ? "bg-pos text-white" : "border border-line-strong text-muted"}`}>{s.done ? <Check className="h-3 w-3" strokeWidth={3} /> : i + 1}</span>
                  <span className={`text-[13px] font-medium ${s.done ? "text-muted line-through" : ""}`}>{s.title}</span>
                </div>
                <p className="text-xs leading-relaxed text-muted">{s.text}</p>
                {!s.done && <Button size="sm" className="mt-auto self-start" onClick={() => nav(s.to)}>{s.cta}</Button>}
              </li>
            ))}
          </ol>
        </Card>
      )}
      <Card className="grid grid-cols-2 divide-line md:grid-cols-4 md:divide-x">
        <Stat className="p-4" label="Simulations" value={fmt.n(list.length)} sub={`${running} in progress`} />
        <Stat className="p-4" label="Mean projected opinion" value={done.length ? fmt.s2(done.reduce((a, s) => a + s.score!, 0) / done.length) : "–"} sub={`across ${done.length} completed runs`} />
        <Stat className="p-4" label="Credit balance" value={fmt.n(usage.data?.credits_balance)} sub={usage.data ? `${usage.data.limits.label} plan · ${usage.data.metered ? "metered" : "own key or dry run"}` : ""} />
        <Stat className="p-4" label="Signals collected" value={fmt.n(pool.data?.signals_total)} sub={`${fmt.n(pool.data?.archive?.snapshots)} hourly snapshots archived`} />
      </Card>

      <div className="mt-5 grid items-start gap-5 xl:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)]">
        <Card className="overflow-hidden">
          <CardHeader title="Recent simulations" divider actions={<Link to="/projects" className="text-[13px] text-brand hover:underline">All projects</Link>} />
          {sims.isLoading ? <div className="space-y-2 p-4"><Skeleton /><Skeleton /><Skeleton /></div>
            : list.length === 0 ? <Empty title="No simulations yet" action={<Button variant="primary" onClick={() => nav("/projects")}>Create a simulation</Button>}>
              Create a project, add a piece of content and test it against the population.</Empty>
              : <SimTable rows={list.slice(0, 10)} />}
        </Card>
        <div className="space-y-5">
          <Card className="overflow-hidden">
            <CardHeader title="Regional context" subtitle="Live inputs agents are conditioned on this hour" divider
              actions={<Link to="/data-pool" className="text-[13px] text-brand hover:underline">Data pool</Link>} />
            {world.isLoading ? <div className="space-y-2 p-4"><Skeleton /><Skeleton /></div> : (
              <table className="dt">
                <thead><tr><th>Region</th><th className="!text-right">Local</th><th className="!text-right">Temp.</th><th>Top story</th></tr></thead>
                <tbody>{Object.values(world.data || {}).map((w: any) => (
                  <tr key={w.region}>
                    <td className="whitespace-nowrap"><span className="mr-2 inline-block h-2 w-2 rounded-[2px]" style={{ background: REGION_COLORS[w.region] }} />{w.city}</td>
                    <td className="r text-muted">{w.local_time?.split(" ").pop()}</td>
                    <td className="r text-muted">{w.weather ? `${Math.round(w.weather.temp_c)}°C` : "–"}</td>
                    <td className="max-w-0 w-full"><div dir="auto" className="truncate text-muted" title={w.news?.[0]?.title || w.brief}>{w.news?.[0]?.title || w.brief}</div></td>
                  </tr>
                ))}</tbody>
              </table>
            )}
          </Card>
          {trend.length > 1 && (
            <Card><CardHeader title="Projected opinion by run" /><div className="px-4 pb-3"><LineSimple points={trend} yMax={10} height={130} xFmt={(v) => `#${v}`} /></div></Card>
          )}
          <Card className="overflow-hidden">
            <CardHeader title="Signals ingested, last 24 hours" divider />
            <table className="dt">
              <thead><tr><th>Source</th><th className="!text-right">Signals</th></tr></thead>
              <tbody>{sources.map(([k, v]) => <tr key={k}><td>{k.replace(/_/g, " ")}</td><td className="r">{fmt.n(v)}</td></tr>)}
                {!sources.length && <tr><td colSpan={2} className="text-muted">No signals yet.</td></tr>}</tbody>
            </table>
          </Card>
        </div>
      </div>
    </Page>
  );
}
