import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Page } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/overlay";
import { Badge, Callout, Card, Empty, Field, Input, Stat } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt } from "@/lib/utils";

type Status = "pending" | "locked" | "scored" | "reference";
interface Direction { previous_product: string; predicted: string; actual: string; correct: boolean; basis: string }
interface LaunchForecast {
  id: string; company: string; product: string; announcement_date: string; release_date: string; context_cutoff: string;
  model_knowledge_cutoff: string | null; simulation_id: string | null; status: Status; prediction_hash: string | null; hash_valid: boolean | null;
  locked_at: string | null; prediction: { score: number; positive_share: number; top_objections: { objection: string }[] } | null;
  outcome: { score: number | null; positive_share?: number; n: number; method: { rater: string; dry: boolean } } | null;
  comparison: { abs_error: number; direction: Direction | null } | null; counts_toward_record: boolean; excluded_because: string[];
  background: { n: number } | null;
}
interface Summary { n: number; companies: number; mean_abs_error: number | null; direction_n: number; direction_hit_rate: number | null; spearman: number | null }
interface Scoreboard { rows: LaunchForecast[]; record: Summary; all: Summary; by_status: Record<Status, number>; contamination_note: string; method: string }

const TONE: Record<Status, "default" | "brand" | "pos" | "info"> = { pending: "default", locked: "brand", scored: "pos", reference: "info" };
const blank = { company: "", product: "", announcement_date: "", release_date: "", model_knowledge_cutoff: "", simulation_id: "",
  youtube: "", reddit: "", background: "" };
const ids = (s: string) => s.split(/[\s,]+/).map((x) => x.trim()).filter(Boolean);

function SummaryRow({ title, s }: { title: string; s?: Summary }) {
  return (
    <div className="mb-5">
      <h2 className="mb-2 text-sm font-semibold">{title}</h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card className="p-4"><Stat label="Scored launches" value={s?.n ?? 0} sub={`${s?.companies ?? 0} companies`} /></Card>
        <Card className="p-4"><Stat label="Mean absolute error" value={fmt.s2(s?.mean_abs_error)} sub="points on the 0-10 scale" /></Card>
        <Card className="p-4"><Stat label="Direction vs previous launch" value={s?.direction_hit_rate == null ? "–" : fmt.pct(s.direction_hit_rate)} sub={`n = ${s?.direction_n ?? 0}`} /></Card>
        <Card className="p-4"><Stat label="Rank correlation" value={s?.spearman == null ? "–" : s.spearman.toFixed(2)} sub="Spearman, needs 3+" /></Card>
      </div>
    </div>
  );
}

export default function LaunchForecastsPage() {
  const orgId = useAuth((s) => s.orgId);
  const qc = useQueryClient();
  const board = useQuery({ queryKey: [orgId, "launch-scoreboard"], queryFn: () => api<Scoreboard>("/launch-forecasts/scoreboard") });
  const sims = useQuery({ queryKey: [orgId, "simulations", "recent"], queryFn: () => api<{ id: string; name: string; status: string; score: number | null }[]>("/simulations?limit=200") });
  const [form, setForm] = useState(blank);
  const set = (k: keyof typeof blank, v: string) => setForm((f) => ({ ...f, [k]: v }));
  const refresh = () => qc.invalidateQueries({ queryKey: [orgId, "launch-scoreboard"] });
  const fail = (e: Error) => toast.error(e.message);
  const create = useMutation({
    mutationFn: () => api("/launch-forecasts", { json: {
      company: form.company, product: form.product, announcement_date: form.announcement_date, release_date: form.release_date,
      model_knowledge_cutoff: form.model_knowledge_cutoff || null, simulation_id: form.simulation_id || null,
      sources: { youtube_video_ids: ids(form.youtube), reddit_query: form.reddit, background_video_ids: ids(form.background) } } }),
    onSuccess: () => { setForm(blank); refresh(); toast.success("Launch added"); }, onError: fail,
  });
  const act = useMutation({
    mutationFn: ({ id, action, body }: { id: string; action: "lock" | "outcome" | "background" | "link" | "delete"; body?: unknown }) =>
      action === "link" ? api(`/launch-forecasts/${id}`, { method: "PATCH", json: body })
        : action === "delete" ? api(`/launch-forecasts/${id}`, { method: "DELETE" })
        : api(`/launch-forecasts/${id}/${action}`, { method: "POST" }),
    onSuccess: (data: any, v) => {
      refresh();
      if (v.action === "background" && data?.seed_text) {
        const url = URL.createObjectURL(new Blob([data.seed_text], { type: "text/plain" }));
        const a = Object.assign(document.createElement("a"), { href: url, download: "launch-background-seed.txt" });
        a.click();
        URL.revokeObjectURL(url);
        toast.success(`${data.n} pre-announcement comments saved as a seed file`);
      }
    },
    onError: fail,
  });
  const completed = (sims.data || []).filter((s) => s.status === "completed").map((s) => ({ value: s.id, label: `${s.name} (${fmt.s1(s.score)})` }));
  const rows = board.data?.rows || [];
  const ready = form.company && form.product && form.announcement_date && form.release_date;

  return (
    <Page title="Launch forecasts" subtitle="Test a product announcement before release, lock the prediction, then score it against the real reaction after launch. Every locked prediction is hashed so it provably predates the outcome.">
      <Callout tone="warn" title="Only launches after the model's training cutoff count" className="mb-5">
        {board.data?.contamination_note || "Language models already know how launches before their training cutoff were received, so those backtests are contaminated."}{" "}
        Simulate with the publish time on or before the announcement so the context only contains data dated before it.
      </Callout>
      <SummaryRow title="Accuracy record (eligible launches only)" s={board.data?.record} />
      <SummaryRow title="All scored launches, including excluded ones" s={board.data?.all} />
      <p className="mb-5 text-xs text-muted">{board.data?.method}</p>

      <Card className="mb-5 space-y-4 p-5">
        <h2 className="font-semibold">Add a launch</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Company"><Input value={form.company} onChange={(e) => set("company", e.target.value)} placeholder="Apple" /></Field>
          <Field label="Product"><Input value={form.product} onChange={(e) => set("product", e.target.value)} placeholder="iPhone 18" /></Field>
          <Field label="Announcement date"><Input type="date" value={form.announcement_date} onChange={(e) => set("announcement_date", e.target.value)} /></Field>
          <Field label="Release date"><Input type="date" value={form.release_date} onChange={(e) => set("release_date", e.target.value)} /></Field>
          <Field label="Model training cutoff" hint="Required to count"><Input type="date" value={form.model_knowledge_cutoff} onChange={(e) => set("model_knowledge_cutoff", e.target.value)} /></Field>
          <Field label="Simulation of the announcement"><Select value={form.simulation_id} onChange={(v) => set("simulation_id", v)} placeholder="Link later" options={completed} /></Field>
          <Field label="Launch / review video ids" hint="After release"><Input value={form.youtube} onChange={(e) => set("youtube", e.target.value)} placeholder="dQw4w9WgXcQ, …" /></Field>
          <Field label="Reddit search" hint="After release"><Input value={form.reddit} onChange={(e) => set("reddit", e.target.value)} placeholder="iPhone 18 review" /></Field>
          <Field label="Previous launch video ids" hint="Background seeds"><Input value={form.background} onChange={(e) => set("background", e.target.value)} /></Field>
        </div>
        <Button variant="primary" disabled={!ready} loading={create.isPending} onClick={() => create.mutate()}>Add launch</Button>
      </Card>

      {!rows.length ? <Card><Empty title="No launches yet">Add an upcoming announcement, simulate it, then lock the prediction before release.</Empty></Card> : (
        <Card className="overflow-x-auto">
          <table className="dt min-w-[980px]">
            <thead><tr><th>Launch</th><th>Released</th><th>Status</th><th className="!text-right">Predicted</th><th className="!text-right">Actual</th>
              <th className="!text-right">Error</th><th>Direction</th><th>Record</th><th /></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.id}>
                <td><div className="font-medium">{r.company} · {r.product}</div>
                  <div className="text-2xs text-muted">Announced {r.announcement_date} · context before {r.context_cutoff.slice(0, 10)}</div>
                  {r.prediction_hash && <div className="num text-2xs text-muted" title={r.prediction_hash}>SHA-256 {r.prediction_hash.slice(0, 12)}… {r.hash_valid ? "verified" : "MISMATCH"}</div>}</td>
                <td>{r.release_date}</td>
                <td><Badge tone={TONE[r.status]}>{r.status}</Badge></td>
                <td className="r">{fmt.s2(r.prediction?.score)}{r.prediction && <div className="text-2xs text-muted">{fmt.pct(r.prediction.positive_share)} positive</div>}</td>
                <td className="r">{fmt.s2(r.outcome?.score)}{r.outcome && <div className="text-2xs text-muted">n = {r.outcome.n}{r.outcome.method.dry ? " · dry run" : ""}</div>}</td>
                <td className="r">{fmt.s2(r.comparison?.abs_error)}</td>
                <td>{r.comparison?.direction ? <span title={r.comparison.direction.basis}>
                  {r.comparison.direction.correct ? "✓" : "✗"} {r.comparison.direction.predicted} / {r.comparison.direction.actual}
                  <div className="text-2xs text-muted">vs {r.comparison.direction.previous_product}</div></span> : "–"}</td>
                <td className="max-w-[220px] text-2xs">{r.counts_toward_record ? <Badge tone="pos">counts</Badge> : <span className="text-muted">{r.excluded_because.join("; ")}</span>}</td>
                <td><div className="flex flex-col items-end gap-1">
                  {r.status === "pending" && !r.simulation_id && <Select value="" onChange={(v) => act.mutate({ id: r.id, action: "link", body: { simulation_id: v } })} placeholder="Link simulation" options={completed} />}
                  {r.simulation_id && <Link className="text-xs text-brand" to={`/simulations/${r.simulation_id}`}>Simulation</Link>}
                  {r.status === "pending" && <Button size="sm" variant="ghost" onClick={() => act.mutate({ id: r.id, action: "background" })}>Background seeds</Button>}
                  {r.status === "pending" && r.simulation_id && <Button size="sm" variant="primary" onClick={() => act.mutate({ id: r.id, action: "lock" })}>Lock prediction</Button>}
                  {(r.status === "locked" || r.status === "scored" || (r.status === "pending" && !r.simulation_id)) &&
                    <Button size="sm" onClick={() => act.mutate({ id: r.id, action: "outcome" })}>{r.outcome ? "Re-collect outcome" : "Collect outcome"}</Button>}
                  {!r.locked_at && <Button size="sm" variant="danger" onClick={() => act.mutate({ id: r.id, action: "delete" })}>Delete</Button>}
                </div></td>
              </tr>))}</tbody>
          </table>
        </Card>
      )}
      <p className="mt-3 text-xs text-muted">A launch without a simulation can still collect its outcome and serves as the reference for the same company's next launch.</p>
    </Page>
  );
}
