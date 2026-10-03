import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge, Bar, Callout, Card, CardHeader, InfoTip, KV, Stat } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { scoreColor } from "@/lib/colors";
import type { Simulation } from "@/lib/types";
import { fmt } from "@/lib/utils";
import PublishedPosts from "./PublishedPosts";

function word(score: number) {
  return score >= 7.5 ? "strongly positive" : score >= 6.5 ? "positive" : score >= 5.5 ? "mildly positive" : score >= 4.5 ? "lukewarm" : score >= 3.5 ? "negative" : "strongly negative";
}

/** Plain-language summary built only from measured results. */
function verdict(r: any, sim: Simulation): string[] {
  const out: string[] = [];
  const sc = r.score;
  out.push(`The audience's reaction is ${word(sc.mean)}: ${sc.mean.toFixed(1)} out of 10 on average, where 5 means "fine, kept scrolling". ` +
    `${fmt.pct(sc.positive)} would rate it 6.5 or higher and ${fmt.pct(sc.negative)} below 4.`);
  const w = r.winners?.[0], l = r.losers?.[0];
  if (w && l) out.push(`It lands best with ${w.label} (${w.score.toFixed(1)}) and worst with ${l.label} (${l.score.toFixed(1)}).`);
  const hm = r.heatmap;
  if (hm?.completion != null && hm.segments?.length > 1) {
    const worst = hm.segments[hm.worst ?? 0];
    out.push(`${fmt.pct(hm.completion)} stay to the end; the biggest drop is at "${worst.label}"${hm.timed && worst.start != null ? ` (${fmt.t(worst.start)})` : ""}, where ${fmt.pct(worst.loss)} leave.`);
  }
  if (r.poll) {
    const lead = r.poll.leader;
    out.push(lead != null ? `In the poll, "${r.poll.options[lead]}" leads with ${fmt.pct(r.poll.share_of_voters[lead])} of votes; ${fmt.pct(r.poll.turnout)} of the audience would vote.`
      : "Almost nobody in the audience would vote in the poll.");
  }
  if (r.ab) {
    const them = r.ab.kind === "competitor";
    out.push(r.ab.winner === "tie" ? `There is no clear difference between ${them ? "your content and the competitor's" : "the two versions"}.`
      : them ? (r.ab.winner === "A" ? `Your content beats the competitor's (${r.ab.a.score.toFixed(2)} vs ${r.ab.b.score.toFixed(2)}).` : `The competitor's content is preferred (${r.ab.b.score.toFixed(2)} vs ${r.ab.a.score.toFixed(2)}).`)
        : `Version ${r.ab.winner} is preferred, with ${fmt.pct(Math.max(r.ab.p_b_better, 1 - r.ab.p_b_better))} confidence.`);
  }
  const rw = r.viral?.cascade?.real_world;
  if (rw) out.push(`Shared through the follower network it reaches a median of ${fmt.n(r.viral.cascade.reach_median)} of the 1M simulated people — very roughly ${fmt.k(rw.median)} real people across these regions.`);
  if (sim.results?.provider?.dry) out.push("This was a dry run without a language model: the numbers exercise the pipeline but are not predictions.");
  return out;
}

export function OverviewPanel({ sim, onTab }: { sim: Simulation; onTab: (t: string) => void }) {
  const r = sim.results || {};
  const nav = useNavigate();
  const bench = useQuery({ queryKey: ["benchmark", sim.id], queryFn: () => api(`/simulations/${sim.id}/benchmark`), enabled: !!r.score });
  const [busy, setBusy] = useState<string | null>(null);
  if (!r.score) return <Callout tone="warn">Results are not available yet.</Callout>;
  const rw = r.viral?.cascade?.real_world;
  const t = r.timing;
  const b = bench.data;

  async function retest(key: string, changes: Record<string, string> = {}, mode: "edit" | "rerun" = "edit") {
    setBusy(key);
    try {
      const n = await api<Simulation>(`/simulations/${sim.id}/clone`, { json: { mode, changes, build: mode === "rerun" || Object.keys(changes).length > 0 } });
      toast.success(mode === "rerun" ? "Re-running with today's live context" : Object.keys(changes).length ? "A/B test created: the same agents will compare both versions" : "Edit version B, then build the graph");
      nav(Object.keys(changes).length || mode === "rerun" ? `/simulations/${n.id}` : `/simulations/${n.id}/edit`);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not create the re-test"); } finally { setBusy(null); }
  }
  const textField = sim.content?.type === "text" ? "text" : "transcript";
  const firstSeg = sim.card?.segments?.[0]?.text || "";
  const withHook = (hook: string) => {
    const src = String(sim.content?.[textField] || "");
    return src && firstSeg && src.includes(firstSeg) ? src.replace(firstSeg, hook) : `${hook} ${src}`.trim();
  };

  return (
    <div className="space-y-5">
      <PublishedPosts sim={sim} />
      {r.creator && <Card className="space-y-3 p-5"><h2 className="font-semibold">Audience and context checks</h2>
        {r.creator.audience_twin && <><p className="text-sm">Matched to your audience breakdown. {r.creator.audience_twin.warning}</p>
          <KV rows={Object.entries(r.creator.audience_twin.coverage || {}).map(([key, value]) => [`Supported ${key}`, `${value}%`])} />
          <p className="text-xs text-muted">Largest difference from your supplied breakdown: {r.creator.audience_twin.max_marginal_error_percent ?? 0} percentage points. Interests and behavior remain synthetic.</p></>}
        {!!r.creator.stale_sources?.length && <div role="status" className="text-sm">{r.creator.stale_sources.map((x: any, i: number) => <p key={i}>{x.region}: {x.source} {x.age_hours == null ? (x.source === "archive" ? "archive unavailable" : "has no recent data") : `was ${x.age_hours} hours old`}</p>)}</div>}
        {r.creator.short_video && <KV rows={[["Rewatch probability", fmt.pct(r.creator.short_video.rewatch_probability)],
          ["Stitch or duet likelihood", fmt.pct(r.creator.short_video.stitch_duet_likelihood)], ["Sound reuse likelihood", fmt.pct(r.creator.short_video.sound_reuse_likelihood)]]} />}
        {!!r.creator.language_fit?.flags?.length && <p className="text-xs text-muted">{r.creator.language_fit.flags.length} language-fit objections. {r.creator.language_fit?.note}</p>}
        {!!r.creator.language_fit?.flags?.length && <table className="dt"><thead><tr><th>Agent</th><th>Language evidence</th></tr></thead><tbody>{r.creator.language_fit.flags.map((x: any) =>
          <tr key={x.agent}><td>{x.agent}</td><td className="whitespace-normal">{x.evidence} · “{x.quote}”</td></tr>)}</tbody></table>}
        <h3 className="text-sm font-medium">Trend fit</h3><p className="text-xs text-muted">{r.trend?.recommendation}</p>
        {!!r.trend?.matches?.length ? <table className="dt"><thead><tr><th>Matching signal</th><th>Phase</th><th>Observed</th></tr></thead><tbody>{r.trend.matches.map((x: any, i: number) =>
          <tr key={i}><td className="whitespace-normal">{x.title}</td><td>{x.phase || "unknown"}</td><td>{x.at ? new Date(x.at).toLocaleDateString() : "Unavailable"}</td></tr>)}</tbody></table> : <p className="text-sm text-muted">No matching regional trends were found for this content.</p>}
      </Card>}
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h2 className="text-base font-semibold">What happened</h2>
          <Button size="sm" loading={busy === "rerun"} onClick={() => retest("rerun", {}, "rerun")} title="Same content and audience, conditioned on this hour's news and trends">
            <RefreshCw className="h-3.5 w-3.5" />Re-run with today's context</Button>
        </div>
        <ul className="mt-3 space-y-2 text-[14px] leading-relaxed">
          {verdict(r, sim).map((s, i) => <li key={i} className="flex gap-2.5"><span className="mt-[9px] h-1.5 w-1.5 shrink-0 rounded-full bg-faint" />{s}</li>)}
        </ul>
      </Card>

      <Card className="grid grid-cols-2 divide-line lg:grid-cols-5 lg:divide-x">
        <Stat className="p-4" label={<span className="inline-flex items-center gap-1">Projected opinion <InfoTip term="opinion" /></span>} value={`${r.score.mean.toFixed(1)} / 10`}
          accent={scoreColor(r.score.mean)} sub={<span className="inline-flex items-center gap-1">95% interval {r.score.low.toFixed(1)}–{r.score.high.toFixed(1)} <InfoTip term="interval" /></span>} />
        <Stat className="p-4" label={<span className="inline-flex items-center gap-1">Completion <InfoTip term="completion" /></span>} value={r.heatmap?.completion != null ? fmt.pct(r.heatmap.completion) : "–"} sub="still paying attention at the end" />
        <Stat className="p-4" label={<span className="inline-flex items-center gap-1">Viral potential <InfoTip term="viral" /></span>} value={`${r.viral.score.toFixed(1)} / 10`} sub={`share intent ${fmt.pct(r.viral.raw.mean_share_intent, 1)}`} />
        <Stat className="p-4" label={<span className="inline-flex items-center gap-1">Estimated reach <InfoTip text={rw?.method} /></span>} value={rw ? `≈ ${fmt.k(rw.median)}` : fmt.n(r.viral.cascade.reach_median)}
          sub={rw ? `${fmt.pct(rw.p_over_1m)} chance of 1M+ people` : "simulated people reached"} />
        <Stat className="p-4" label={<span className="inline-flex items-center gap-1">Benchmark <InfoTip term="benchmark" /></span>}
          value={b?.available ? `${b.percentile}th pct` : "–"} sub={b?.available ? `vs ${fmt.n(b.n)} runs · ${b.scope}` : b?.reason || "Loading…"} />
      </Card>

      <Card className="overflow-hidden">
        <CardHeader title="Fix it: what to change" divider subtitle="Ranked by estimated impact. Estimates come from this run's own measurements; test a change to measure it." />
        {(r.recommendations || []).length === 0 && <div className="px-4 py-5 text-[13px] text-muted">No clear weaknesses stood out in this run.</div>}
        <div className="divide-y divide-line">
          {(r.recommendations || []).map((x: any) => (
            <div key={x.id} className="grid gap-3 px-4 py-3.5 md:grid-cols-[110px_minmax(0,1fr)_auto]">
              <div><Badge tone={x.area === "Risk" ? "neg" : "outline"}>{x.area}</Badge></div>
              <div className="min-w-0">
                <div className="text-[14px] font-medium">{x.title}</div>
                <p className="mt-0.5 text-[13px] leading-relaxed text-muted">{x.detail}</p>
                {x.evidence && <p className="mt-1 border-l-2 border-line-strong pl-2.5 text-xs text-muted">“{x.evidence}”</p>}
              </div>
              <div className="flex flex-col items-start gap-2 md:items-end">
                {x.impact && <div className="text-right"><div className="num text-[14px] font-semibold text-pos">{x.impact.estimate}</div><div className="text-xs text-muted">{x.impact.metric} · {x.impact.basis}</div></div>}
                {x.action?.type === "retest" && <Button size="sm" loading={busy === x.id} onClick={() => retest(x.id)}>Edit and re-test</Button>}
              </div>
            </div>
          ))}
        </div>
      </Card>

      {r.rewrites ? (
        <Card className="overflow-hidden">
          <CardHeader title="Suggested rewrites" divider subtitle={`Written by ${r.rewrites.model} from the objections and drop-offs above. "Test this" runs an A/B test where the same agents compare it with the original.`} />
          <div className="divide-y divide-line">
            {r.rewrites.titles.map((x: any, i: number) => (
              <Rewrite key={`t${i}`} kind="Title" text={x.text} why={x.why} busy={busy === `t${i}`} onTest={() => retest(`t${i}`, { title: x.text })} />
            ))}
            {r.rewrites.hook && <Rewrite kind="Opening" text={r.rewrites.hook.text} why={r.rewrites.hook.why} busy={busy === "hook"}
              onTest={() => retest("hook", { [textField]: withHook(r.rewrites.hook.text) })} />}
            {r.rewrites.ctas.map((x: any, i: number) => <Rewrite key={`c${i}`} kind="Call to action" text={x.text} why={x.why} />)}
            {r.rewrites.edits.map((x: any, i: number) => <Rewrite key={`e${i}`} kind={x.area[0].toUpperCase() + x.area.slice(1)} text={x.change} why={x.why} />)}
          </div>
        </Card>
      ) : sim.report_status === "done" && r.provider?.dry ? (
        <Callout tone="info" title="Rewrite suggestions need a language model">Connect a provider under Settings and re-run to get title, opening and call-to-action rewrites you can test with one click.</Callout>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-2">
        {r.poll && <PollCard p={r.poll} />}
        {r.ab && <CompareCard ab={r.ab} onMore={() => onTab("analytics")} />}
        {t && (
          <Card className="overflow-hidden">
            <CardHeader title="When to publish" divider subtitle="From the audience's activity patterns and the live calendar." />
            <div className="px-4 py-3">
              <div className="text-[15px] font-semibold">{String(t.best_window_local[0]).padStart(2, "0")}:00 – {String(t.best_window_local[1]).padStart(2, "0")}:00 <span className="font-normal text-muted">{t.city} time</span></div>
              <div className="mt-2 flex h-14 items-end gap-px" aria-label="Audience activity by hour (UTC)">
                {t.activity_utc.map((v: number, h: number) => <div key={h} title={`${h}:00 UTC · ${fmt.pct(v)}`} className="flex-1 rounded-t-[2px]" style={{ height: `${Math.max(4, v * 100)}%`, background: (h === t.best_window_utc[0] || h === (t.best_window_utc[0] + 1) % 24) ? "rgb(var(--brand))" : "rgb(var(--line-strong))" }} />)}
              </div>
              <div className="mt-1 flex justify-between text-[11px] text-muted"><span>00 UTC</span><span>12</span><span>23</span></div>
              <KV className="mt-3" rows={[
                ...(t.peak_in_simulation ? [["Conversation peaked", `${t.peak_in_simulation.hours_after_publish} h after posting (${t.peak_in_simulation.local_time})`] as [string, string]] : []),
                ...t.per_region.slice(0, 4).map((p: any) => [`${p.city} peak`, `${String(p.best_local_hour).padStart(2, "0")}:00 local`] as [string, string]),
                ...(t.upcoming.length ? [["Coming up", t.upcoming.slice(0, 2).map((u: any) => `${u.name} (${u.days_away} d)`).join(", ")] as [string, string]] : []),
              ]} />
            </div>
          </Card>
        )}
        {b?.available && (
          <Card className="overflow-hidden">
            <CardHeader title="How it ranks" divider subtitle={b.method} />
            <div className="px-4 py-3">
              <div className="relative mt-2 h-2 rounded-sm bg-line">
                <div className="absolute top-1/2 h-4 w-0.5 -translate-y-1/2 bg-fg" style={{ left: `${b.percentile}%` }} />
              </div>
              <div className="mt-1 flex justify-between text-[11px] text-muted"><span>Bottom</span><span>Median {b.median}</span><span>Top</span></div>
              <KV className="mt-3" rows={[["Percentile in " + b.scope, `${b.percentile}th of ${fmt.n(b.n)}`], ["Top 10% starts at", b.top10_threshold.toFixed(2)],
                ["Gap to the top 10%", b.gap_to_top10 > 0 ? `+${b.gap_to_top10.toFixed(2)}` : "Already in the top 10%"],
                ["Your workspace average", b.workspace_average != null ? `${b.workspace_average.toFixed(2)} over ${b.workspace_runs} runs` : "–"]]} />
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

function Rewrite({ kind, text, why, onTest, busy }: { kind: string; text: string; why?: string; onTest?: () => void; busy?: boolean }) {
  return (
    <div className="grid gap-3 px-4 py-3 md:grid-cols-[110px_minmax(0,1fr)_auto]">
      <div><Badge tone="outline">{kind}</Badge></div>
      <div className="min-w-0"><div dir="auto" className="text-[14px]">{text}</div>{why && <div className="mt-0.5 text-xs text-muted">{why}</div>}</div>
      <div>{onTest && <Button size="sm" loading={busy} onClick={onTest}>Test this</Button>}</div>
    </div>
  );
}

function PollCard({ p }: { p: any }) {
  return (
    <Card className="overflow-hidden">
      <CardHeader title="Poll results" divider subtitle={`${fmt.pct(p.turnout)} of the audience would vote. ${p.method}`} />
      <div className="space-y-2.5 px-4 py-3">
        {p.options.map((o: string, i: number) => (
          <div key={i}>
            <div className="mb-1 flex justify-between text-[13px]"><span className={i === p.leader ? "font-semibold" : ""}>{o}</span><span className="num">{fmt.pct(p.share_of_voters[i])}</span></div>
            <Bar value={p.share_of_voters[i]} />
          </div>
        ))}
      </div>
      {p.by?.region?.length > 0 && (
        <div className="overflow-x-auto border-t border-line">
          <table className="dt">
            <thead><tr><th>Region</th>{p.options.map((o: string, i: number) => <th key={i} className="!text-right">{o.length > 14 ? `${o.slice(0, 13)}…` : o}</th>)}</tr></thead>
            <tbody>{p.by.region.map((row: any) => <tr key={row.label}><td>{row.label} <span className="text-xs text-muted">n={row.n}</span></td>{row.shares.map((s: number, i: number) => <td key={i} className="r">{fmt.pct(s)}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function CompareCard({ ab, onMore }: { ab: any; onMore: () => void }) {
  const them = ab.kind === "competitor";
  const rows: [string, string, (v: number) => string][] = [["Opinion", "score", (v) => v.toFixed(2)], ["Share intent", "would_share", (v) => fmt.pct(v, 1)],
    ["Comment intent", "would_comment", (v) => fmt.pct(v, 1)], ["Completion", "completion", (v) => fmt.pct(v)], ["Emotional pull", "emotion", (v) => fmt.pct(v)], ["Originality", "novelty", (v) => fmt.pct(v)]];
  return (
    <Card className="overflow-hidden">
      <CardHeader title={them ? "You vs the competitor" : "Version A vs version B"} divider
        subtitle={ab.winner === "tie" ? "No clear winner on opinion." : `${them ? (ab.winner === "A" ? "You lead" : "The competitor leads") : `Version ${ab.winner} is preferred`} · same ${ab.paired_n} agents saw both.`}
        actions={<Button size="sm" variant="ghost" onClick={onMore}>Details</Button>} />
      <table className="dt">
        <thead><tr><th>Measure</th><th className="!text-right">{them ? "You" : "A"}</th><th className="!text-right">{them ? "Competitor" : "B"}</th><th className="!text-right">Gap</th></tr></thead>
        <tbody>{rows.filter(([, k]) => ab.a[k] != null && ab.b[k] != null).map(([label, k, f]) => {
          const d = ab.a[k] - ab.b[k];
          return <tr key={k}><td>{label}</td><td className="r">{f(ab.a[k])}</td><td className="r">{f(ab.b[k])}</td>
            <td className={`r font-medium ${Math.abs(d) < 1e-3 ? "text-muted" : d > 0 ? "text-pos" : "text-neg"}`}>{d > 0 ? "+" : ""}{k === "score" ? d.toFixed(2) : `${(d * 100).toFixed(1)} pts`}</td></tr>;
        })}</tbody>
      </table>
    </Card>
  );
}
