import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronRight, Copy, Download, History, Info, Loader2, MessageSquare, MoreHorizontal, PencilLine, Send, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { LiveGraph, type GraphHandle } from "@/components/graph/LiveGraph";
import { Button } from "@/components/ui/button";
import { Menu } from "@/components/ui/overlay";
import { Badge, Switch } from "@/components/ui/primitives";
import { api, API, ApiError } from "@/lib/api";
import { can, useAuth } from "@/lib/auth";
import type { GEdge, GNode, Simulation } from "@/lib/types";
import { cn } from "@/lib/utils";
import { AgentSheet } from "./AgentSheet";
import { CollabSheet, REVIEW, ReviewStatus } from "./CollabSheet";
import { EnvironmentStep } from "./steps/EnvironmentStep";
import { GraphStep } from "./steps/GraphStep";
import { InteractionStep } from "./steps/InteractionStep";
import { ReportStep } from "./steps/ReportStep";
import { SimulationStep } from "./steps/SimulationStep";
import { useSimulationStream } from "./useSimulationStream";

const STEPS = [
  { n: 1, key: "graph", label: "Knowledge graph", sub: "Entities and live context" },
  { n: 2, key: "environment", label: "Environment", sub: "Agents and run settings" },
  { n: 3, key: "simulation", label: "Simulation", sub: "Feed and forum activity" },
  { n: 4, key: "report", label: "Results", sub: "Report and analysis" },
  { n: 5, key: "interaction", label: "Interviews", sub: "Agent chat and surveys" },
];

export const STATUS_TONE: Record<string, "default" | "brand" | "pos" | "neg" | "warn" | "info"> = {
  draft: "default", building_graph: "info", graph_ready: "brand", preparing: "info", ready: "brand", queued: "warn", running: "warn",
  paused: "warn", completed: "pos", failed: "neg", cancelled: "default",
};
export const STATUS_LABEL: Record<string, string> = {
  draft: "Draft", building_graph: "Building graph", graph_ready: "Graph ready", preparing: "Preparing", ready: "Ready to run", queued: "Queued",
  running: "Running", paused: "Paused", completed: "Completed", failed: "Failed", cancelled: "Cancelled",
};

export function reachable(sim: Simulation): number {
  const st = sim.status;
  if (st === "completed") return sim.report_status === "done" ? 5 : 4;
  if (["queued", "running", "paused"].includes(st)) return 3;
  if (st === "ready") return 3;
  if (["graph_ready", "preparing"].includes(st)) return 2;
  if (st === "failed") return sim.config?.agents ? 3 : sim.ontology?.entity_types ? 2 : 1;
  return 1;
}

export default function SimulationPage() {
  const { simId } = useParams();
  const qc = useQueryClient();
  const nav = useNavigate();
  const orgId = useAuth((s) => s.orgId);
  const graphRef = useRef<GraphHandle>(null);
  const [step, setStep] = useState<number | null>(null);
  const [scheduling, setScheduling] = useState(false);
  const [selected, setSelected] = useState<GNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<GEdge | null>(null);
  const [agentRef, setAgentRef] = useState<string | null>(null);
  const [team, setTeam] = useState<{ open: boolean; tab: "comments" | "versions"; anchor: string }>({ open: false, tab: "comments", anchor: "general" });

  const q = useQuery({ queryKey: [orgId, "sim", simId], queryFn: () => api<Simulation>(`/simulations/${simId}`), refetchInterval: (qq) => {
    const data = qq.state.data as Simulation | undefined;
    const st = data?.status;
    return st && (["building_graph", "preparing", "queued", "running", "paused"].includes(st)
      || (st === "completed" && !["done", "failed"].includes(data?.report_status || ""))) ? 4000 : false;
  } });
  const refetch = useCallback(() => { qc.invalidateQueries({ queryKey: [orgId, "sim", simId] }); }, [qc, orgId, simId]);
  const stream = useSimulationStream(simId, graphRef, (t) => {
    refetch();
    if (t === "graph.completed") toast.success("Knowledge graph ready");
    if (t === "env.completed") toast.success("Environment ready");
    if (t === "simulation.completed") { toast.success("Simulation complete. The analyst is writing the report."); setStep(4); }
    if (t === "report.completed") toast.success("Report ready");
    if (t.endsWith(".failed")) toast.error("A step failed. See the details on the page.");
  });

  useEffect(() => {
    if (selected && step === 1) {
      const frame = requestAnimationFrame(() => graphRef.current?.focus(selected.id));
      return () => cancelAnimationFrame(frame);
    }
  }, [selected, step]);
  const sim = q.data;
  const project = useQuery({ queryKey: [orgId, "project", sim?.project_id], queryFn: () => api<{ name: string }>(`/projects/${sim!.project_id}`), enabled: !!sim?.project_id, staleTime: 60_000 });
  useEffect(() => {
    if (sim && step === null) {
      const r = reachable(sim);
      setStep(sim.status === "running" || sim.status === "paused" || sim.status === "queued" ? 3 : Math.min(r, sim.status === "completed" ? 4 : r));
    }
  }, [sim, step]);

  if (q.isLoading || !sim) return <div className="flex h-full items-center justify-center text-muted"><Loader2 className="h-5 w-5 animate-spin" /></div>;
  const reach = reachable(sim);
  const cur = step ?? 1;
  const busy = ["building_graph", "preparing", "queued", "running", "paused"].includes(sim.status);
  const liveGraph = sim.status === "running" || sim.status === "building_graph" || sim.status === "paused";

  async function clone() {
    const n = await api<Simulation>(`/simulations/${simId}/clone`, { json: { mode: "edit" } });
    toast.success("Re-test draft created with an editable version B");
    nav(`/simulations/${n.id}/edit`);
  }
  async function schedule(enabled: boolean) {
    setScheduling(true);
    try {
      await api(`/simulations/${simId}/rerun-schedule`, { method: "PUT", json: { every_days: enabled ? 7 : null } });
      await qc.invalidateQueries({ queryKey: [orgId, "sim", simId] });
      toast.success(enabled ? "Weekly re-runs enabled with fresh news and trends" : "Weekly re-runs disabled");
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not update schedule"); }
    finally { setScheduling(false); }
  }
  async function review(status: string) {
    const note = status === "changes_requested" ? prompt("What should change?") ?? "" : "";
    try {
      await api(`/simulations/${simId}/review`, { json: { status, note } });
      toast.success(REVIEW[status].label);
      refetch();
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not update the review status"); }
  }
  const openTeam = (tab: "comments" | "versions", anchor = "general") => setTeam({ open: true, tab, anchor });
  async function remove() {
    if (!confirm("Delete this simulation and everything it produced?")) return;
    await api(`/simulations/${simId}`, { method: "DELETE" });
    nav(`/projects/${sim!.project_id}`);
  }
  async function exportJson() {
    const r = await fetch(`${API}/simulations/${simId}/export`, { headers: { Authorization: `Bearer ${useAuth.getState().accessToken}`, "X-Org-Id": orgId || "" } });
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `kruvim-${simId}.json`;
    a.click();
  }

  const showGraph = cur <= 3;
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-line bg-panel px-4 pt-4 sm:px-6">
        <div className="flex items-center gap-1.5 text-[13px] text-muted">
          <Link to="/projects" className="hover:text-fg">Projects</Link><ChevronRight className="h-3 w-3" />
          <Link to={`/projects/${sim.project_id}`} className="max-w-[240px] truncate hover:text-fg">{project.data?.name ?? "Project"}</Link><ChevronRight className="h-3 w-3" />
          <span className="text-fg/80">{sim.name}</span>
        </div>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <h1 className="truncate text-xl font-semibold">{sim.name}</h1>
            <Badge tone={STATUS_TONE[sim.status]}>{busy && <span className="h-1.5 w-1.5 animate-pulse2 rounded-full bg-current" />}{STATUS_LABEL[sim.status]}</Badge>
            {sim.ab && <Badge tone="outline">A/B test</Badge>}
            {sim.results?.provider?.dry && <Badge tone="warn">Dry run</Badge>}
            {stream.connected === "error" && <Badge tone="neg">Reconnecting…</Badge>}
            {sim.review_status && sim.review_status !== "none" && <ReviewStatus status={sim.review_status} />}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {(sim.status === "completed" || sim.rerun_every_days) && can("member") && <div title={sim.next_rerun_at ? `Next run: ${new Date(sim.next_rerun_at).toLocaleString()}` : "Runs the same content with fresh news every week; normal usage limits apply."}><Switch checked={!!sim.rerun_every_days} disabled={scheduling} onChange={schedule} label="Re-run every week" /></div>}
            <Button size="sm" variant="ghost" onClick={() => openTeam("comments")}><MessageSquare className="h-3.5 w-3.5" />Comments</Button>
            <Button size="sm" variant="ghost" onClick={() => openTeam("versions")}><History className="h-3.5 w-3.5" />Versions</Button>
            <Button size="sm" onClick={() => nav(`/simulations/${simId}/edit`)} disabled={busy}><PencilLine className="h-3.5 w-3.5" />Edit inputs</Button>
            <Button size="sm" onClick={clone}><Copy className="h-3.5 w-3.5" />Re-test an edit</Button>
            <Menu trigger={<Button size="icon-sm" variant="ghost" aria-label="More actions"><MoreHorizontal className="h-4 w-4" /></Button>} items={[
              ...(sim.status === "completed" ? [
                { label: "Submit for review", icon: <Send className="h-3.5 w-3.5" />, onSelect: () => review("in_review") },
                ...(can("admin") ? [{ label: "Approve", icon: <Check className="h-3.5 w-3.5" />, onSelect: () => review("approved") },
                  { label: "Request changes", icon: <PencilLine className="h-3.5 w-3.5" />, onSelect: () => review("changes_requested") }] : []),
                "sep" as const] : []),
              { label: "Export JSON", icon: <Download className="h-3.5 w-3.5" />, onSelect: exportJson },
              "sep",
              { label: "Delete simulation", icon: <Trash2 className="h-3.5 w-3.5" />, onSelect: remove, danger: true },
            ]} />
          </div>
        </div>
        <div className="mt-4 flex overflow-x-auto">
          {STEPS.map((s) => {
            const done = s.n < reach || (s.n === reach && ((s.n === 4 && sim.report_status === "done") || (s.n === 3 && sim.status === "completed")));
            const active = cur === s.n;
            const locked = s.n > reach;
            return (
              <button key={s.n} disabled={locked} onClick={() => setStep(s.n)}
                className={cn("group relative flex min-w-[150px] flex-1 items-center gap-2.5 px-3 pb-3 pt-1 text-left transition-colors",
                  !active && !locked && "hover:bg-raised/60", locked && "cursor-not-allowed opacity-50")}>
                <div className={cn("num flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full border text-xs font-semibold",
                  done ? "border-pos bg-pos text-white" : active ? "border-brand bg-brand text-white" : "border-line-strong bg-panel text-muted")}>
                  {done ? <Check className="h-3 w-3" strokeWidth={3} /> : s.n}
                </div>
                <div className="min-w-0">
                  <div className={cn("truncate text-[13px] font-medium", active ? "text-fg" : "text-muted")}>{s.label}</div>
                  <div className="truncate text-xs text-faint">{s.sub}</div>
                </div>
                {active && <div className="absolute inset-x-0 bottom-0 h-0.5 bg-brand" />}
              </button>
            );
          })}
        </div>
      </div>

      <StepIntro step={cur} sim={sim} />
      <div className={cn("min-h-0 flex-1", showGraph ? "flex flex-col overflow-y-auto lg:grid lg:grid-cols-[minmax(380px,0.9fr)_minmax(0,1.3fr)] lg:overflow-hidden" : "overflow-y-auto")}>
        <div className={cn(showGraph ? "min-w-0 border-line lg:min-h-0 lg:overflow-y-auto lg:border-r" : "")}>
          {cur === 1 && <GraphStep sim={sim} stream={stream} onNext={() => setStep(2)} refetch={refetch} />}
          {cur === 2 && <EnvironmentStep sim={sim} stream={stream} onNext={() => setStep(3)} refetch={refetch} onAgent={setAgentRef} />}
          {cur === 3 && <SimulationStep sim={sim} stream={stream} refetch={refetch} onAgent={setAgentRef} graphRef={graphRef} />}
          {cur === 4 && <ReportStep sim={sim} stream={stream} onAgent={setAgentRef} onComment={(a) => openTeam("comments", a)} onSource={(source) => {
            if (source.agent_ref) { setAgentRef(source.agent_ref); return; }
            const node = stream.nodes.find((n) => n.id === source.node_id);
            if (node) { setSelected(node); setSelectedEdge(stream.edges.find((e) => e.id === source.edge_id) || null); setStep(1); }
            else toast.info("This source is no longer in the graph. Reopen the report for its latest sources.");
          }} />}
          {cur === 5 && <InteractionStep sim={sim} stream={stream} />}
        </div>
        {showGraph && (
          <div className="relative order-first h-[58vh] min-h-[360px] min-w-0 shrink-0 p-3 lg:order-none lg:h-auto lg:min-h-0">
            <LiveGraph ref={graphRef} nodes={stream.nodes} edges={stream.edges} version={stream.graphVersion} live={liveGraph}
              opinions={stream.opinions} selectedId={selected?.id} selectedEdgeId={selectedEdge?.id} height="100%" title="Knowledge and social graph"
              defaultHidden={cur >= 3 ? [] : []}
              onSelect={(n) => { setSelected(n); setSelectedEdge(null); if (n?.kind === "agent") setAgentRef(n.id.slice(6)); }} />
            {selected && (selected.kind !== "agent" || selectedEdge) && (
              <div className="absolute right-6 top-[60px] z-10 w-80 rounded-md border border-line bg-panel p-3.5 shadow-pop animate-fade-in">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-[13px] font-semibold">{selected.label}</div>
                    <div className="mt-0.5 flex gap-1"><Badge>{selected.kind}</Badge><Badge tone="outline">{selected.type}</Badge></div>
                  </div>
                  <button className="text-xs text-muted hover:text-fg" onClick={() => { setSelected(null); setSelectedEdge(null); }}>Close</button>
                </div>
                {selected.summary && <p className="mt-2 text-xs leading-relaxed text-muted">{selected.summary}</p>}
                {selectedEdge && <div className="mt-2 rounded border border-brand/40 bg-brand/10 p-2 text-xs" aria-label="Cited graph fact">
                  <div className="font-semibold">{selectedEdge.relation.replace(/_/g, " ")}</div>
                  <p className="mt-1">{selectedEdge.fact}</p>
                  <p className="mt-1 text-muted">Round {selectedEdge.valid_from_round ?? selectedEdge.round}{selectedEdge.valid_until_round != null ? ` – superseded in round ${selectedEdge.valid_until_round}` : " – current fact"}</p>
                </div>}
                <div className="mt-3 max-h-56 space-y-1.5 overflow-y-auto">
                  {stream.edges.filter((e) => (typeof e.source === "string" ? e.source : e.source.id) === selected.id || (typeof e.target === "string" ? e.target : e.target.id) === selected.id)
                    .slice(0, 30).map((e, i) => {
                      const other = (typeof e.source === "string" ? e.source : e.source.id) === selected.id ? e.target : e.source;
                      const o = typeof other === "string" ? other : other.label;
                      return (
                        <div key={i} className="rounded border border-line bg-raised px-2 py-1.5 text-2xs">
                          <span className="text-brand">{e.relation.replace(/_/g, " ")}</span> <span className="text-fg/80">{o}</span>
                          {e.fact && <div className="mt-0.5 text-muted">{e.fact.slice(0, 160)}</div>}
                        </div>
                      );
                    })}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
      <AgentSheet simId={sim.id} agentRef={agentRef} onClose={() => setAgentRef(null)} onChat={() => { setAgentRef(null); setStep(5); }} />
      <CollabSheet sim={sim} open={team.open} tab={team.tab} anchor={team.anchor} onClose={() => setTeam({ ...team, open: false })} onChanged={refetch} />
    </div>
  );
}

const INTRO: Record<number, (s: Simulation) => string> = {
  1: () => "Kruvim reads your content, maps the people, brands and topics in it, and links them to what is happening in each region right now.",
  2: () => "Choose how many agents take part and for how long. Kruvim picks a representative sample of the audience and the accounts that would join the conversation.",
  3: (s) => s.status === "completed" ? "The simulation has finished. Scroll the activity log or watch the graph to see how the conversation unfolded."
    : "Agents see the post in their feeds, react, comment, share and change their minds. Pause, speed up or inject a news event at any time.",
  4: () => "Start with the overview: what happened, what to change and how it ranks. The analyst report and detailed analytics go deeper.",
  5: () => "Ask any agent why they reacted the way they did, question the analyst, or survey a whole group with one question.",
};

function StepIntro({ step, sim }: { step: number; sim: Simulation }) {
  return (
    <div className="flex items-start gap-2 border-b border-line bg-raised/60 px-4 py-2 text-[13px] text-muted sm:px-6">
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-faint" /><span>{INTRO[step]?.(sim)}</span>
    </div>
  );
}
