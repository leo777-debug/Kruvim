import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Loader2, RefreshCw } from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Callout, Empty, UnderlineTabs } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { Simulation } from "@/lib/types";
import { cn } from "@/lib/utils";
import { OverviewPanel } from "../results/OverviewPanel";
import { ResultsPanels } from "../results/ResultsPanels";
import { ActionHistory } from "../results/ActionHistory";
import { TranscriptPanel } from "../results/TranscriptPanel";
import type { StreamState } from "../useSimulationStream";

export function ReportStep({ sim, stream, onAgent, onComment }: { sim: Simulation; stream: StreamState; onAgent: (r: string) => void; onComment?: (anchor: string) => void }) {
  const [tab, setTab] = useState("overview");
  const rep = useQuery({ queryKey: ["report", sim.id, sim.report_status, stream.report.status], queryFn: () => api(`/simulations/${sim.id}/report`),
    enabled: sim.status === "completed" });
  const r = rep.data;
  const running = sim.report_status === "running" || sim.report_status === "queued" || stream.report.status === "running";
  const sections = r?.status === "done" ? r.sections : Object.entries(stream.report.sections).sort((a, b) => +a[0] - +b[0]).map(([, v]) => v);
  const outline = r?.status === "done" ? { title: r.title, summary: r.summary } : stream.report.outline;
  const log = r?.status === "done" && r.log?.length ? r.log : stream.report.log;

  async function regenerate() {
    try {
      await api(`/simulations/${sim.id}/report`, { method: "POST" });
      toast.success("The analyst is rewriting the report");
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
  }

  if (sim.status !== "completed") {
    return <div className="bg-panel"><Empty title="Results appear when the simulation completes">Run the simulation in step 3 first.</Empty></div>;
  }
  return (
    <div className="mx-auto max-w-[1500px] px-4 py-5 sm:px-6">
      <UnderlineTabs value={tab} onChange={setTab} className="mb-5" tabs={[
        { key: "overview", label: "Overview" },
        { key: "report", label: "Analyst report", badge: running ? <Loader2 className="h-3 w-3 animate-spin text-brand" /> : undefined },
        { key: "results", label: "Detailed analytics" },
        { key: "transcript", label: "Transcript" },
      ]} />
      {tab === "report" && (
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
          <article className="card min-w-0 px-5 py-6 sm:px-10 sm:py-8">
            {!outline && running && <div className="space-y-3"><div className="skeleton h-7 w-2/3" /><div className="skeleton h-4 w-full" /><div className="skeleton h-4 w-5/6" /></div>}
            {outline && (
              <div className="prose-report">
                <div className="mb-2 text-xs text-muted">Analyst report{r?.model ? ` · ${r.model}` : ""}{r?.created_at ? ` · ${new Date(r.created_at).toLocaleString()}` : ""}</div>
                <h1>{outline.title}</h1>
                <p className="text-muted">{outline.summary}</p>
                {(sections || []).map((s: any, i: number) => (
                  <section key={i} className="animate-fade-in">
                    <h2>{s.title}</h2>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{s.content}</ReactMarkdown>
                  </section>
                ))}
                {running && <div className="mt-6 flex items-center gap-2 text-xs text-muted"><Loader2 className="h-3.5 w-3.5 animate-spin" />Writing the next section…</div>}
              </div>
            )}
            {sim.report_status === "failed" && <Callout tone="neg" title="The report failed">{r?.error || stream.lastError}</Callout>}
            {!running && <div className="mt-8 border-t border-line pt-4"><Button size="sm" onClick={regenerate}><RefreshCw className="h-3.5 w-3.5" />Regenerate report</Button></div>}
          </article>
          <aside className="min-w-0 space-y-3">
            <div className="card sticky top-4">
              <div className="flex items-center justify-between border-b border-line px-4 py-3">
                <div className="section-title">Analysis log</div>
                <span className="num text-xs text-muted">{log.length} steps</span>
              </div>
              <div className="max-h-[calc(100vh-240px)] space-y-1.5 overflow-y-auto p-3">
                {log.length === 0 && <div className="p-4 text-center text-[13px] text-muted">Queries and reasoning steps behind each section appear here.</div>}
                {log.map((l: any, i: number) => <LogEntry key={i} l={l} title={outline?.sections?.[l.section] || (sections?.[l.section] as any)?.title} />)}
              </div>
            </div>
          </aside>
        </div>
      )}
      {tab === "overview" && <OverviewPanel sim={sim} onTab={(t) => setTab(t === "analytics" ? "results" : t)} />}
      {tab === "results" && <ResultsPanels sim={sim} onAgent={onAgent} onComment={onComment} />}
      {tab === "transcript" && <><TranscriptPanel sim={sim} onAgent={onAgent} /><ActionHistory simId={sim.id} /></>}
    </div>
  );
}

function LogEntry({ l, title }: { l: any; title?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={cn("rounded-md border px-2.5 py-2 text-xs", l.final ? "border-pos/30 bg-pos/[0.04]" : "border-line")}>
      <button className="flex w-full items-start gap-1.5 text-left" onClick={() => setOpen(!open)}>
        {l.observation ? (open ? <ChevronDown className="mt-0.5 h-3 w-3 shrink-0 text-muted" /> : <ChevronRight className="mt-0.5 h-3 w-3 shrink-0 text-muted" />) : <span className="w-3" />}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-muted">Section {(l.section ?? 0) + 1}{title ? `: ${title}` : ""}</span>
            {l.tool && <span className="mono ml-auto shrink-0 rounded-sm border border-line bg-raised px-1.5 text-[11px] text-fg">{l.tool}</span>}
            {l.final && <span className="ml-auto shrink-0 text-pos">Written</span>}
          </div>
          {l.thought && <div className="mt-0.5 leading-relaxed text-fg">{l.thought}</div>}
          {l.input && Object.keys(l.input).length > 0 && <div className="mono mt-0.5 truncate text-[11px] text-muted">{JSON.stringify(l.input)}</div>}
        </div>
      </button>
      {open && l.observation && <pre className="mono mt-1.5 max-h-48 overflow-auto whitespace-pre-wrap rounded border border-line bg-raised p-2 text-[11px] text-muted">{l.observation}</pre>}
    </div>
  );
}
