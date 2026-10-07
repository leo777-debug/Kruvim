import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Callout, Card } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Simulation } from "@/lib/types";
import { fmt } from "@/lib/utils";
import type { StreamState } from "./useSimulationStream";

export function SimpleResults({ sim, stream, onDetails, onAgent, refetch }: {
  sim: Simulation; stream: StreamState; onDetails: () => void; onAgent: (ref: string) => void; refetch: () => void;
}) {
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const orgId = useAuth((state) => state.orgId);
  const accuracy = useQuery({queryKey: [orgId, "creator-accuracy", sim.content.platform], queryFn: () => api<any>(`/analytics/summary?platform=${encodeURIComponent(sim.content.platform || "tiktok")}`), enabled: sim.status === "completed"});
  const r = sim.results;
  const complete = sim.status === "completed" && !!r?.score;
  const quick = sim.progress?.quick_read;
  const stage = ["draft", "building_graph", "graph_ready"].includes(sim.status) ? 0 : ["preparing", "ready", "queued"].includes(sim.status) ? 1 : sim.status === "running" || sim.status === "paused" ? 2 : 3;
  const stages = ["Reading your content", "Building the audience", "Showing it to people", "Writing your results"];
  const part = stage === 0 ? stream.graphProgress?.progress || 0 : stage === 1 ? stream.envProgress?.progress || 0 : stage === 2 ? (sim.progress?.round || 0) / Math.max(1, sim.progress?.rounds || 1) : sim.report_status === "done" ? 1 : .7;
  const progress = Math.min(100, (stage + part) * 25);
  const fix = r?.recommendations?.[0];
  const worst = r?.heatmap?.segments?.[r.heatmap.worst ?? 0];
  async function action(path: string) {
    setBusy(true);
    try { await api(`/simulations/${sim.id}/${path}`, { method: "POST" }); refetch(); }
    catch (e) { toast.error(e instanceof Error ? e.message : "Could not start the test"); }
    finally { setBusy(false); }
  }
  async function retest() {
    setBusy(true);
    try {
      const field = sim.content.type === "text" ? "text" : "transcript";
      const hook = r.rewrites?.hook?.text;
      const first = sim.card?.segments?.[0]?.text;
      const original = String(sim.content[field] || "");
      const changes = hook ? { [field]: first && original.includes(first) ? original.replace(first, hook) : `${hook} ${original}` } : {};
      const next = await api<Simulation>(`/simulations/${sim.id}/clone`, { json: { mode: "edit", changes, build: !!hook } });
      if (!hook && fix) {
        await api(`/simulations/${next.id}`, { method: "PATCH", json: { requirement: `${sim.requirement || ""}\nCheck this improvement: ${fix.title}. ${fix.detail}`.slice(0, 4000) } });
        toast.info("Your draft is ready. Apply the suggested fix, then press Test it.");
      }
      nav(hook ? `/simulations/${next.id}` : `/simulations/${next.id}/edit`);
    } catch (e) { toast.error(e instanceof Error ? e.message : "Could not create a re-test"); }
    finally { setBusy(false); }
  }
  return <div className="space-y-5">
    {Object.entries(accuracy.data?.calibration || {}).filter(([, value]: any) => value.n >= 3).map(([metric, value]: any) => <p className="text-sm text-muted" key={metric}>Across your last {value.n} predictions on this platform, average {metric === "retention" ? "watch percentage" : metric} error was {value.mean_absolute_error} {value.unit}.</p>)}
    {(sim.status === "failed" || sim.report_status === "failed") && <Callout tone="neg" title="This test could not finish" action={<Button loading={busy} onClick={() => action("retry")}>Retry</Button>}>{sim.error || "Try again to finish the results."}</Callout>}
    {sim.status === "draft" && <Button variant="primary" loading={busy} onClick={() => action("autopilot")}>Test it</Button>}
    {sim.report_status !== "done" && sim.status !== "failed" && <Card className="space-y-3 p-5">
      <p className="font-medium">{stages[stage]}</p><div role="progressbar" aria-label="Test progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress)} className="h-2 overflow-hidden rounded-full bg-raised"><div className="h-full bg-brand transition-all" style={{ width: `${progress}%` }} /></div>
      <p className="text-xs text-muted">{sim.status === "paused" ? "Your test is paused. Open See how it works to resume it." : "You can leave this page and come back to your results."}</p>
    </Card>}
    {!complete && quick && <Card className="p-5" role="status"><h2 className="font-semibold">Quick read: {quick.score.toFixed(1)} / 10</h2><p className="mt-2 text-sm text-muted">First impressions from {quick.sample_size} simulated people. This small sample is preliminary; the score will change as the full test finishes.</p></Card>}
    {complete && <>
      <Card className="space-y-4 border-brand/30 p-5 sm:p-7" aria-label="Verdict">
        <div className="flex flex-wrap items-baseline gap-3"><span className="num text-4xl font-semibold">{r.score.mean.toFixed(1)}<span className="text-lg text-muted"> / 10</span></span><h2 className="text-xl font-semibold">{r.score.mean >= 6.5 ? "Most people like it" : r.score.mean >= 4.5 ? "It needs a stronger reason to watch" : "It needs a rethink"}</h2></div>
        <p className="text-xs text-muted">Predicted reaction from simulated people{r.provider?.dry ? " · Dry run" : ""}. {r.population_provenance?.label || "Audience estimate, source pending"}.</p>
        {r.creator_analytics?.forecast?.usual_multiple != null && <p className="text-sm">About <strong>{r.creator_analytics.forecast.usual_multiple}× your usual views</strong>, based on {r.creator_analytics.forecast.calibration_n} linked predictions on this platform. This is an uncertain estimate.</p>}
        {!r.creator_analytics?.forecast?.views && r.creator_analytics?.baseline?.medians?.views != null && <p className="text-sm text-muted">Your usual views: {fmt.n(r.creator_analytics.baseline.medians.views)}. A relative forecast needs three linked model predictions made before publication.</p>}
        <div className="grid gap-4 sm:grid-cols-2"><div><h3 className="text-sm font-semibold">Who loves it</h3><p className="mt-1 text-sm">{r.winners?.[0]?.label || "No clear standout yet"}</p></div><div><h3 className="text-sm font-semibold">Who needs more convincing</h3><p className="mt-1 text-sm">{r.losers?.[0]?.label || "No clear weaker group"}</p></div></div>
        {["video", "audio"].includes(sim.content.type) && worst && <p className="text-sm">The biggest drop is at <strong>{worst.label}</strong>{r.heatmap.timed && worst.start != null ? ` (${fmt.t(worst.start)})` : ""}: {fmt.pct(worst.loss)} stop paying attention.</p>}
        <div className="border-t border-line pt-4"><h3 className="font-semibold">The most important fix</h3><p className="mt-1 text-sm">{fix?.title || "Keep the strongest part and try a new opening"}</p>{fix?.detail && <p className="mt-1 text-sm text-muted">{fix.detail}</p>}<Button className="mt-3" variant="primary" loading={busy} onClick={retest}>Re-test with this fix</Button></div>
      </Card>
      <Card className="p-5"><h2 className="mb-3 font-semibold">What people said</h2><p className="mb-3 text-xs text-muted">Simulated reactions, not real follower feedback.</p>{[...(r.winners || []), ...(r.losers || [])].filter((g) => g.evidence).slice(0, 4).map((g) => <blockquote className="mb-4 border-l-2 border-line pl-3 text-sm" key={g.key}><p>“{g.evidence.quote}”</p><button className="mt-1 text-xs text-brand" onClick={() => onAgent(g.evidence.agent)}>{g.evidence.name} · {g.label}</button></blockquote>)}</Card>
      <Card className="p-5"><h2 className="mb-3 font-semibold">Who it reaches</h2><div className="grid gap-3 sm:grid-cols-3">{(r.groups?.region || []).map((g: any) => <div key={g.key} className="rounded border border-line p-3 text-sm"><strong>{g.label}</strong><p className="mt-1">{g.score.toFixed(1)} / 10</p><p className="text-xs text-muted">{fmt.pct(g.share_of_audience)} of your chosen audience</p></div>)}</div></Card>
      <Card className="p-5"><h2 className="mb-3 font-semibold">Fixes</h2>{(r.recommendations || []).slice(1, 4).map((x: any) => <div key={x.id} className="mb-4 text-sm"><h3 className="font-medium">{x.title}</h3><p className="mt-1 text-muted">{x.detail}</p></div>)}<Button onClick={onDetails}>Details</Button><p className="mt-2 text-xs text-muted">Full report, charts, transcript, graph and method.</p></Card>
    </>}
  </div>;
}
