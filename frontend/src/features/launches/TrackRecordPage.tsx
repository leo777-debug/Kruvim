import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Lock, Plus, ShieldCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Page } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Dialog, Select } from "@/components/ui/overlay";
import { Badge, Callout, Card, CardHeader, Empty, Field, Input, Stat, Textarea } from "@/components/ui/primitives";
import { QueryGate } from "@/components/ui/states";
import { api, ApiError } from "@/lib/api";
import { can, useAuth } from "@/lib/auth";
import type { SimSummary } from "@/lib/types";
import { fmt } from "@/lib/utils";

export interface TrackRecord {
  id: string; source: "forecast" | "launch"; question: string; domain: string; country: string; kind: "numeric" | "binary"; metric: string;
  threshold: number | null; resolves_on: string; status: "draft" | "locked" | "resolved" | "void"; locked_at: string | null;
  prediction_hash: string | null; public?: boolean; predicted: number | null; low: number | null; high: number | null; baseline: number;
  baseline_method: string; outcome: number | null; happened?: boolean; evidence_url: string | null; excluded: string[];
  scores: { abs_error?: number; baseline_abs_error?: number; inside_interval?: boolean; brier?: number; baseline_brier?: number } | null;
}
export interface Summary {
  counted: number; excluded: number; voided: number; open: number;
  numeric: { n: number; mae: number; baseline_mae: number; skill: number | null; interval_coverage: number | null; interval_coverage_ci: number[] | null } | null;
  binary: { n: number; brier: number; baseline_brier: number; skill: number | null; calibration: { range: string; n: number; mean_predicted: number; observed: number; observed_ci: number[] | null }[] } | null;
}

const pct = (x?: number | null) => (x == null ? "–" : `${Math.round(x * 100)}%`);
const metricLabel = (m: string) => (m === "score" ? "reaction score" : "positive share");
export function predictionText(r: TrackRecord) {
  if (r.predicted == null) return "–";
  if (r.kind === "binary") return `${pct(r.predicted)} chance ${metricLabel(r.metric)} ≥ ${r.threshold}`;
  const v = r.metric === "score" ? r.predicted.toFixed(1) : pct(r.predicted);
  return r.low != null && r.high != null ? `${v} (${r.metric === "score" ? `${r.low.toFixed(1)}–${r.high.toFixed(1)}` : `${pct(r.low)}–${pct(r.high)}`})` : v;
}
const outcomeText = (r: TrackRecord) => r.outcome == null ? "–" : r.kind === "binary" ? `${r.happened ? "Yes" : "No"} (${r.outcome})` : r.metric === "score" ? r.outcome.toFixed(1) : pct(r.outcome);
const statusTone = { draft: "default", locked: "brand", resolved: "pos", void: "neg" } as const;

export function SummaryCards({ summary }: { summary: Summary }) {
  const n = summary.numeric, b = summary.binary;
  return (
    <Card className="grid grid-cols-2 divide-line md:grid-cols-4 md:divide-x">
      <Stat className="p-4" label="Forecasts that count" value={fmt.n(summary.counted)} sub={`${summary.open} open · ${summary.excluded} excluded · ${summary.voided} voided`} />
      <Stat className="p-4" label="Error vs baseline" value={n ? `${n.mae.toFixed(2)} vs ${n.baseline_mae.toFixed(2)}` : "–"} sub={n?.skill != null ? `${n.skill >= 0 ? "Beats" : "Worse than"} the baseline by ${Math.abs(Math.round(n.skill * 100))}%` : "Mean absolute error, numeric forecasts"} />
      <Stat className="p-4" label="Outcomes inside the 95% range" value={pct(n?.interval_coverage)} sub={n?.interval_coverage_ci ? `95% CI ${pct(n.interval_coverage_ci[0])}–${pct(n.interval_coverage_ci[1])} · target 95%` : "Target 95%"} />
      <Stat className="p-4" label="Yes/no Brier score" value={b ? `${b.brier.toFixed(3)} vs ${b.baseline_brier.toFixed(3)}` : "–"} sub={b?.skill != null ? `Skill ${Math.round(b.skill * 100)}% (lower Brier is better)` : "Lower is better"} />
    </Card>
  );
}

export function Calibration({ summary }: { summary: Summary }) {
  if (!summary.binary?.calibration.length) return null;
  return (
    <Card className="overflow-hidden">
      <CardHeader title="Calibration" subtitle="When Kruvim gave a chance in this range, how often did it happen? A well-calibrated forecaster's bars match their range." divider />
      <div className="overflow-x-auto" tabIndex={0} data-scroll-region>
        <table className="dt">
          <thead><tr><th>Predicted</th><th className="!text-right">Forecasts</th><th className="!text-right">Average predicted</th><th className="!text-right">Happened</th><th>95% range of “happened”</th></tr></thead>
          <tbody>{summary.binary.calibration.map((c) => (
            <tr key={c.range}><td>{c.range}</td><td className="r">{c.n}</td><td className="r">{pct(c.mean_predicted)}</td><td className="r">{pct(c.observed)}</td>
              <td><div className="relative h-2 w-40 rounded-full bg-raised" role="img" aria-label={`Observed ${pct(c.observed)}, range ${pct(c.observed_ci?.[0])} to ${pct(c.observed_ci?.[1])}, predicted ${pct(c.mean_predicted)}`}>
                {c.observed_ci && <div className="absolute h-2 rounded-full bg-brand/30" style={{ left: `${c.observed_ci[0] * 100}%`, width: `${(c.observed_ci[1] - c.observed_ci[0]) * 100}%` }} />}
                <div className="absolute -top-0.5 h-3 w-0.5 bg-fg" style={{ left: `${c.mean_predicted * 100}%` }} /></div></td></tr>
          ))}</tbody>
        </table>
      </div>
    </Card>
  );
}

const today = () => new Date().toISOString().slice(0, 10);
const blank = { question: "", domain: "launch", country: "AE", kind: "numeric", metric: "score", threshold: "6.5", resolution_criteria: "", resolves_on: "",
  baseline_value: "5", baseline_method: "neutral midpoint (5.0)", model_knowledge_cutoff: "", simulation_id: "", public: false };

export default function TrackRecordPage() {
  const orgId = useAuth((s) => s.orgId);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: [orgId, "track-record"], queryFn: () => api<{ summary: Summary; records: TrackRecord[]; public_enabled: boolean }>("/track-record") });
  const sims = useQuery({ queryKey: [orgId, "sims-for-forecasts"], queryFn: () => api<SimSummary[]>("/simulations?limit=100") });
  const ledger = useQuery({ queryKey: ["ledger-head"], queryFn: () => api<{ head: string; length: number }>("/public/ledger?limit=1"), meta: { silent: true } });
  const [open, setOpen] = useState(false);
  const [f, setF] = useState<typeof blank>(blank);
  const [resolving, setResolving] = useState<TrackRecord | null>(null);
  const [outcome, setOutcome] = useState({ value: "", evidence_url: "", note: "" });
  const refresh = () => { qc.invalidateQueries({ queryKey: [orgId, "track-record"] }); qc.invalidateQueries({ queryKey: ["ledger-head"] }); };
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong.");
  const create = useMutation({
    mutationFn: () => api("/forecasts", { json: { ...f, threshold: f.kind === "binary" ? Number(f.threshold) : null, baseline_value: Number(f.baseline_value),
      model_knowledge_cutoff: f.model_knowledge_cutoff || null, simulation_id: f.simulation_id || null } }),
    onSuccess: () => { toast.success("Forecast saved as a draft. Lock it to put it on the record."); setOpen(false); setF(blank); refresh(); }, onError: fail,
  });
  const lock = useMutation({ mutationFn: (id: string) => api(`/forecasts/${id}/lock`, { method: "POST" }), onSuccess: () => { toast.success("Locked and added to the public ledger."); refresh(); }, onError: fail });
  const resolve = useMutation({
    mutationFn: () => api(`/forecasts/${resolving!.id}/resolve`, { json: { ...outcome, value: Number(outcome.value) } }),
    onSuccess: () => { toast.success("Resolved and scored."); setResolving(null); refresh(); }, onError: fail,
  });
  const voidIt = useMutation({ mutationFn: ({ id, reason }: { id: string; reason: string }) => api(`/forecasts/${id}/void`, { json: { reason } }), onSuccess: refresh, onError: fail });
  async function proof(r: TrackRecord) {
    try {
      const p = await api(`/forecasts/${r.id}/proof`);
      const url = URL.createObjectURL(new Blob([JSON.stringify(p, null, 2)], { type: "application/json" }));
      const a = document.createElement("a"); a.href = url; a.download = `kruvim-forecast-proof-${r.id}.json`; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { fail(e); }
  }
  const set = (k: keyof typeof blank) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  const completed = (sims.data || []).filter((s) => s.status === "completed");

  return (
    <Page title="Track record" subtitle="Forecasts locked before their outcome, chained in a public hash ledger, and scored against a simple baseline so the record can't flatter itself."
      actions={can("member") && <Button variant="primary" onClick={() => setOpen(true)}><Plus className="h-3.5 w-3.5" />New forecast</Button>}>
      <QueryGate query={q} what="the track record">
        {(data) => (
          <div className="space-y-5">
            <SummaryCards summary={data.summary} />
            {data.summary.counted < 20 && <Callout tone="info" title="Early days">With fewer than 20 scored forecasts the numbers swing a lot; read the ranges, not the headline. Dry runs, forecasts locked late and questions the model could already know never count.</Callout>}
            <Calibration summary={data.summary} />
            <Card className="overflow-hidden">
              <CardHeader title="Forecasts" divider subtitle={<>Includes your <Link className="text-brand" to="/launches">launch forecasts</Link>. Locked forecasts can't be edited or deleted; voided ones stay visible.</>} />
              {!data.records.length ? <Empty icon={<ShieldCheck className="h-5 w-5" />} title="No forecasts yet">Run a simulation that answers a question with a known resolution date, then create a forecast from it and lock it before the outcome is known.</Empty> : (
                <div className="overflow-x-auto" tabIndex={0} data-scroll-region>
                  <table className="dt min-w-[900px]">
                    <thead><tr><th>Question</th><th>Prediction</th><th>Baseline</th><th>Outcome</th><th>Status</th><th className="!text-right"><span className="sr-only">Actions</span></th></tr></thead>
                    <tbody>{data.records.map((r) => (
                      <tr key={`${r.source}-${r.id}`}>
                        <td className="max-w-[320px]"><div className="font-medium">{r.question}</div>
                          <div className="text-2xs text-muted">{r.domain} · {r.country} · resolves {fmt.day(r.resolves_on)}{r.prediction_hash ? <> · <span className="mono" title={r.prediction_hash}>#{r.prediction_hash.slice(0, 10)}</span></> : null}{r.public ? " · public" : ""}</div>
                          {r.excluded.length > 0 && r.status !== "draft" && <div className="text-2xs text-muted">Doesn't count: {r.excluded.join("; ")}</div>}</td>
                        <td>{predictionText(r)}</td>
                        <td><div>{r.kind === "binary" ? pct(r.baseline) : r.metric === "score" ? r.baseline.toFixed(1) : pct(r.baseline)}</div><div className="text-2xs text-muted">{r.baseline_method}</div></td>
                        <td>{outcomeText(r)}{r.evidence_url && <div className="text-2xs"><a className="text-brand" href={r.evidence_url} target="_blank" rel="noreferrer noopener">evidence</a></div>}
                          {r.scores && <div className="text-2xs text-muted">{r.kind === "binary" ? `Brier ${r.scores.brier} vs ${r.scores.baseline_brier}` : `off by ${r.scores.abs_error} vs ${r.scores.baseline_abs_error}`}</div>}</td>
                        <td><Badge tone={statusTone[r.status]}>{r.status}</Badge></td>
                        <td className="whitespace-nowrap !text-right">{r.source === "forecast" && <>
                          {r.status === "draft" && can("member") && <Button size="sm" onClick={() => lock.mutate(r.id)} loading={lock.isPending && lock.variables === r.id}><Lock className="h-3.5 w-3.5" />Lock</Button>}
                          {r.status === "locked" && can("member") && r.resolves_on <= today() && <Button size="sm" onClick={() => { setOutcome({ value: "", evidence_url: "", note: "" }); setResolving(r); }}>Resolve</Button>}
                          {r.status !== "draft" && <Button size="sm" variant="ghost" aria-label={`Download proof for: ${r.question}`} onClick={() => proof(r)}><Download className="h-3.5 w-3.5" /></Button>}
                          {(r.status === "locked" || r.status === "resolved") && can("admin") && <Button size="sm" variant="ghost" onClick={() => { const reason = window.prompt("Why void this forecast? (it stays visible on the record)"); if (reason) voidIt.mutate({ id: r.id, reason }); }}>Void</Button>}
                        </>}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              )}
            </Card>
            <Card className="p-4 text-[13px]">
              <div className="flex items-start gap-2"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-pos" aria-hidden /><div>
                <div className="font-medium">Public hash ledger</div>
                <p className="text-muted">Every lock and resolution is chained: each entry's hash covers the one before, so no past prediction can change without breaking every later hash. The ledger holds hashes only. {ledger.data ? <>{fmt.n(ledger.data.length)} entries · head <span className="mono">{ledger.data.head.slice(0, 16)}…</span> · </> : null}<a className="text-brand" href="/api/v1/public/ledger" target="_blank" rel="noreferrer">view it</a>.
                  {data.public_enabled ? <> The <Link className="text-brand" to="/record">public scoreboard</Link> is live.</> : " The public scoreboard is off; a platform administrator turns it on."}</p>
              </div></div>
            </Card>
          </div>
        )}
      </QueryGate>

      <Dialog open={open} onOpenChange={setOpen} title="New forecast" footer={<><Button onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" type="submit" form="forecast-form" loading={create.isPending}>Save draft</Button></>}>
        <form id="forecast-form" className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
          <Field label="Question"><Input required minLength={8} maxLength={400} value={f.question} onChange={set("question")} placeholder="Will the new phone launch land well with UAE viewers?" /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Simulation that answers it"><Select value={f.simulation_id || "-"} onChange={(v) => setF({ ...f, simulation_id: v === "-" ? "" : v })}
              options={[{ value: "-", label: "Choose later" }, ...completed.map((s) => ({ value: s.id, label: s.name }))]} /></Field>
            <Field label="Resolves on"><Input type="date" required min={today()} value={f.resolves_on} onChange={set("resolves_on")} /></Field>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <Field label="Type"><Select value={f.kind} onChange={(v) => setF({ ...f, kind: v, metric: "score", baseline_value: v === "binary" ? "0.5" : "5", baseline_method: v === "binary" ? "coin flip (50%)" : "neutral midpoint (5.0)" })}
              options={[{ value: "numeric", label: "A number" }, { value: "binary", label: "Yes / no" }]} /></Field>
            <Field label="Measure"><Select value={f.metric} onChange={(v) => setF({ ...f, metric: v })} options={[{ value: "score", label: "Reaction score (0-10)" }, ...(f.kind === "numeric" ? [{ value: "positive_share", label: "Share positive (0-1)" }] : [])]} /></Field>
            {f.kind === "binary" ? <Field label="Reaches at least"><Input type="number" step="0.1" min={0.1} max={9.9} required value={f.threshold} onChange={set("threshold")} /></Field>
              : <Field label="Country"><Input required maxLength={8} value={f.country} onChange={set("country")} /></Field>}
          </div>
          <Field label="How it will be measured" help="Be specific enough that anyone would get the same answer: source, sample, time window."><Textarea required minLength={20} value={f.resolution_criteria} onChange={set("resolution_criteria")} className="min-h-[72px]" /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={f.kind === "binary" ? "Baseline probability" : "Baseline value"} help="The simple answer Kruvim must beat."><Input type="number" step="0.01" required value={f.baseline_value} onChange={set("baseline_value")} /></Field>
            <Field label="Baseline is"><Input required maxLength={300} value={f.baseline_method} onChange={set("baseline_method")} /></Field>
          </div>
          <Field label="Model training cutoff" help="Forecasts resolving before the model's training data ends don't count: it may already know the answer."><Input type="date" value={f.model_knowledge_cutoff} onChange={set("model_knowledge_cutoff")} /></Field>
          <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={f.public} onChange={(e) => setF({ ...f, public: e.target.checked })} />Show on the public scoreboard (can't be changed after locking)</label>
        </form>
      </Dialog>

      <Dialog open={!!resolving} onOpenChange={(o) => !o && setResolving(null)} title="Resolve forecast" footer={<><Button onClick={() => setResolving(null)}>Cancel</Button><Button variant="primary" type="submit" form="resolve-form" loading={resolve.isPending}>Resolve and score</Button></>}>
        <form id="resolve-form" className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); resolve.mutate(); }}>
          <p className="text-[13px] text-muted">{resolving?.question}</p>
          <Field label={`Measured ${resolving ? metricLabel(resolving.metric) : ""}`}><Input type="number" step="0.01" required value={outcome.value} onChange={(e) => setOutcome({ ...outcome, value: e.target.value })} /></Field>
          <Field label="Evidence link"><Input type="url" required value={outcome.evidence_url} onChange={(e) => setOutcome({ ...outcome, evidence_url: e.target.value })} placeholder="https://" /></Field>
          <Field label="Note" hint="Optional"><Input maxLength={1000} value={outcome.note} onChange={(e) => setOutcome({ ...outcome, note: e.target.value })} /></Field>
        </form>
      </Dialog>
    </Page>
  );
}
