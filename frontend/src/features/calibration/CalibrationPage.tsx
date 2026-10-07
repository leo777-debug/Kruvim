import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Page } from "@/components/layout/AppShell";
import { Card, Empty, Stat } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt, platformName } from "@/lib/utils";
import AccuracyReport from "./AccuracyReport";
import { Link } from "react-router-dom";

export default function CalibrationPage() {
  const orgId = useAuth((s) => s.orgId);
  const nav = useNavigate();
  const q = useQuery({ queryKey: [orgId, "calibration"], queryFn: () => api("/calibration") });
  const weights = useQuery({ queryKey: [orgId, "source-weights"], queryFn: () => api<{ sources: Record<string, { n: number; weight: number }>; minimum: number; method: string }>("/calibration/source-weights") });
  const c = q.data;
  const imported = useQuery({queryKey: [orgId, "analytics-summary"], queryFn: () => api<any>("/analytics/summary")});
  return (
    <Page title="Calibration" subtitle="Linked analytics update real results automatically. Rank correlation measures how well predictions track actual outcomes across your runs.">
      <AccuracyReport />
      <Card className="mb-5 space-y-3 p-5"><h2 className="font-semibold">Your imported post outcomes</h2><p className="text-sm text-muted">{imported.data?.linked || 0} posts linked to tests. Dry runs and predictions made after publication are excluded from these error estimates.</p>{Object.entries(imported.data?.calibration || {}).map(([metric, value]: any) => <p className="text-sm" key={metric}>{metric === "retention" ? "Average % watched" : metric}: average error {value.mean_absolute_error} {value.unit} across your last {value.n} comparable predictions.</p>)}{!Object.keys(imported.data?.calibration || {}).length && <p className="text-sm text-muted">Link imported posts to tests made with a connected model before publication to measure their accuracy.</p>}<Link className="text-sm text-brand" to="/my-audience">Import analytics or link a post</Link></Card>
      <p className="mb-5 text-sm"><Link to="/my-audience" className="text-brand">Connect analytics</Link> · <Link to="/accuracy" className="text-brand">View the public accuracy report</Link></p>
      <Card className="mb-5 space-y-3 p-5"><h2 className="font-semibold">Does simulated memory improve accuracy?</h2>
        <p className="text-xs text-muted">{c?.memory_comparison?.method || "Compare first-impression predictions from memory and Fresh audience tests against linked real outcomes. This comparison stays within your workspace."}</p>
        {!c?.memory_comparison?.available ? <p className="text-sm text-muted">Not enough comparable outcomes yet. Complete at least three live-model tests with memory and three with Fresh audience on, on the same platform and format, then link their real outcomes.</p> :
          <div className="overflow-x-auto"><table className="dt"><thead><tr><th>Platform / format</th><th>Outcome</th><th>Memory error</th><th>Fresh error</th><th>Tests</th></tr></thead>
            <tbody>{c.memory_comparison.comparisons.map((row: any) => <tr key={`${row.platform}:${row.format}:${row.metric}`}>
              <td>{platformName(row.platform)} · {row.format?.replaceAll("_", " ")}</td><td>{row.metric.replaceAll("_", " ")} ({row.unit})</td>
              <td>{row.memory_error.toFixed(3)}</td><td>{row.fresh_error.toFixed(3)}</td><td>{row.memory_n} memory / {row.fresh_n} fresh</td>
            </tr>)}</tbody></table></div>}
        <p className="text-xs text-muted">Lower held-out error is better. These observational results do not automatically increase memory's influence.</p>
      </Card>
      <Card className="mb-5 p-5"><h2 className="mb-2 font-semibold">Data source weights</h2><p className="text-xs text-muted">{weights.data?.method}</p>
        <table className="dt mt-3"><thead><tr><th>Source</th><th>Tests</th><th>Weight</th></tr></thead><tbody>{Object.entries(weights.data?.sources || {}).map(([key, value]) =>
          <tr key={key}><td>{key}</td><td>{value.n}</td><td>{value.weight.toFixed(2)}</td></tr>)}</tbody></table>
        {!Object.keys(weights.data?.sources || {}).length && <p className="mt-2 text-sm text-muted">Equal weights until enough consenting workspaces contribute at least {weights.data?.minimum || 20} tests per source.</p>}
      </Card>
      {!c || c.n === 0 ? <Card><Empty title="No real-world results yet">Open a completed simulation, go to Results, then Analytics, and record the outcome under Calibration.</Empty></Card> : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {Object.entries(c.correlations).length === 0 && <Card className="col-span-full p-4 text-[13px] text-muted">At least 3 reports with the same metric are needed for a correlation.</Card>}
            {Object.entries(c.correlations).map(([k, v]: any) => {
              const [pred, real] = k.split("~");
              return <Card key={k} className="p-4"><Stat label={`${pred.replace("predicted_", "")} vs ${real.replace("_", " ")}`} value={v.rho == null ? "–" : v.rho.toFixed(2)}
                accent={v.rho > 0.3 ? "rgb(var(--pos))" : v.rho < 0 ? "rgb(var(--neg))" : undefined} sub={`n = ${v.n}`} /></Card>;
            })}
          </div>
          <Card className="mt-5 overflow-x-auto">
            <table className="dt min-w-[760px]">
              <thead><tr><th>Simulation</th><th>Platform</th><th className="!text-right">Predicted opinion</th><th className="!text-right">Predicted virality</th>
                <th className="!text-right">Views</th><th className="!text-right">Engagement</th><th className="!text-right">Watched</th></tr></thead>
              <tbody>{c.rows.map((r: any, i: number) => (
                <tr key={i} onClick={() => nav(`/simulations/${r.simulation_id}`)} className="hoverable">
                  <td className="font-medium">{r.name}</td><td>{platformName(r.platform)}</td>
                  <td className="r">{fmt.s2(r.predicted_score)}</td><td className="r">{fmt.s1(r.predicted_viral)}</td>
                  <td className="r">{fmt.n(r.views)}</td><td className="r">{r.engagement_rate != null ? `${r.engagement_rate}%` : "–"}</td>
                  <td className="r">{r.retention != null ? `${r.retention}%` : "–"}</td>
                </tr>))}</tbody>
            </table>
          </Card>
        </>
      )}
    </Page>
  );
}
