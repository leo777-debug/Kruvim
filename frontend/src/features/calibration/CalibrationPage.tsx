import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Page } from "@/components/layout/AppShell";
import { Card, Empty, Stat } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt } from "@/lib/utils";

export default function CalibrationPage() {
  const orgId = useAuth((s) => s.orgId);
  const nav = useNavigate();
  const q = useQuery({ queryKey: [orgId, "calibration"], queryFn: () => api("/calibration") });
  const c = q.data;
  return (
    <Page title="Calibration" subtitle="Predictions only matter if they track reality. Record real results on each simulation's report; Kruvim measures rank correlation (Spearman ρ) between predictions and outcomes across your runs. Publish this number even when it is imperfect.">
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
                  <td className="font-medium">{r.name}</td><td>{r.platform}</td>
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
