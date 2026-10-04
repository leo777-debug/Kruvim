import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { BarList, Dumbbell, HeatGrid, Histogram, LineSimple, OpinionTimeline, PopulationScatter, ReachChart, SERIES } from "@/components/charts";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/overlay";
import { Badge, Bar, Callout, Card, CardHeader, Field, Input, KV, Segmented, Stat } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { engColor, REGION_COLORS, scoreColor, STANCE_COLORS } from "@/lib/colors";
import { useReference } from "@/lib/queries";
import type { Simulation } from "@/lib/types";
import { cn, fmt, platformName } from "@/lib/utils";

const SECTIONS = [
  ["verdict", "Summary"], ["attention", "Attention"], ["audience", "Audience"], ["dynamics", "Conversation"], ["spread", "Reach"], ["platforms", "Platforms"],
  ["psychology", "Psychology"], ["ab", "A/B test"], ["population", "Population"], ["context", "Context"], ["calibrate", "Calibration"], ["run", "Method"],
] as const;

export function ResultsPanels({ sim, onAgent, onComment }: { sim: Simulation; onAgent: (r: string) => void; onComment?: (anchor: string) => void }) {
  const r = sim.results || {};
  if (!r.score) return <Callout tone="warn">Results are not available yet.</Callout>;
  const go = (id: string) => document.getElementById(`res-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  return (
    <div>
      <nav className="sticky top-0 z-10 mb-5 flex gap-0.5 overflow-x-auto border-b border-line bg-bg py-1.5">
        {SECTIONS.filter(([k]) => k !== "ab" || r.ab).map(([k, l]) => (
          <button key={k} onClick={() => go(k)} className="whitespace-nowrap rounded-md px-2.5 py-1 text-[13px] text-muted hover:bg-raised hover:text-fg">{l}</button>
        ))}
      </nav>
      <div className="space-y-10">
        <Verdict r={r} />
        <Attention r={r} sim={sim} onComment={onComment} />
        <Audience r={r} sim={sim} onAgent={onAgent} />
        <Dynamics r={r} onAgent={onAgent} />
        <Spread r={r} />
        <Platforms r={r} />
        <Psychology r={r} />
        {r.ab && <AB r={r} />}
        <Population r={r} onAgent={onAgent} />
        <Context sim={sim} r={r} />
        <Calibrate sim={sim} />
        <Run r={r} sim={sim} />
      </div>
    </div>
  );
}

function S({ id, title, sub, children }: { id: string; title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section id={`res-${id}`} className="scroll-mt-16">
      <div className="mb-3"><h2 className="text-base font-semibold">{title}</h2>{sub && <p className="mt-0.5 text-[13px] text-muted">{sub}</p>}</div>
      {children}
    </section>
  );
}

function Verdict({ r }: { r: any }) {
  const sc = r.score, v = r.viral;
  return (
    <S id="verdict" title="Summary" sub={`Projected over ${fmt.n(r.audience.size)} agents in the audience; ${r.audience.voice_n} interviewed, ${fmt.n(r.audience.crowd_n)} simulated as crowd.`}>
      <div className="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)_minmax(0,1fr)]">
        <Card className="p-5">
          <div className="eyebrow">Projected opinion</div>
          <div className="num mt-1.5 flex items-center gap-2.5 text-[40px] font-semibold leading-none"><span className="h-3.5 w-3.5 rounded-[3px]" style={{ background: scoreColor(sc.mean) }} aria-hidden />{sc.mean.toFixed(1)}<span className="text-base font-normal text-muted">/ 10</span></div>
          <div className="num mt-1.5 text-xs text-muted">95% interval {sc.low.toFixed(2)} to {sc.high.toFixed(2)}</div>
          <div className="mt-4"><Histogram counts={sc.hist} mean={sc.mean} /></div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
            <div><div className="text-xs text-muted">Rate 6.5 or higher</div><div className="num font-medium text-pos">{fmt.pct(sc.positive)}</div></div>
            <div><div className="text-xs text-muted">Rate below 4</div><div className="num font-medium text-neg">{fmt.pct(sc.negative)}</div></div>
          </div>
        </Card>
        <Card className="p-5">
          <div className="eyebrow mb-3">First impression and after discussion</div>
          <div className="grid grid-cols-2 gap-4">
            <Stat label="Voice, first impression" value={fmt.s2(sc.first_impression)} accent={scoreColor(sc.first_impression)} />
            <Stat label="Voice, after discussion" value={fmt.s2(sc.after_discussion)} accent={scoreColor(sc.after_discussion)} />
            <Stat label="Crowd, first impression" value={fmt.s2(sc.crowd_first)} accent={scoreColor(sc.crowd_first)} />
            <Stat label="Crowd, final" value={fmt.s2(sc.crowd_final)} accent={scoreColor(sc.crowd_final)} />
          </div>
          {r.timeline?.length > 1 && <div className="mt-4"><OpinionTimeline data={r.timeline} height={140} /></div>}
        </Card>
        <Card className="p-5">
          <div className="flex items-baseline justify-between"><div className="eyebrow">Viral potential</div><div className="num text-2xl font-semibold">{v.score.toFixed(1)}<span className="ml-1 text-sm font-normal text-muted">/ 10</span></div></div>
          <div className="mt-4 space-y-2">
            {Object.entries(v.factors).map(([k, x]: any) => (
              <div key={k} className="grid grid-cols-[130px_1fr_40px] items-center gap-2 text-xs">
                <span className="capitalize text-muted">{k.replace(/_/g, " ")}</span><Bar value={x} /><span className="num text-right">{fmt.pct(x)}</span>
              </div>
            ))}
          </div>
          <KV className="mt-4 border-t border-line pt-1" rows={[["Views in simulation", fmt.n(v.in_simulation.views)], ["Reposts in simulation", fmt.n(v.in_simulation.reposts)], ["Median reach, 1M graph", fmt.n(v.cascade.reach_median)]]} />
        </Card>
      </div>
    </S>
  );
}

function Attention({ r, sim, onComment }: { r: any; sim: Simulation; onComment?: (anchor: string) => void }) {
  const hm = r.heatmap;
  const [sel, setSel] = useState<number>(hm.worst ?? 0);
  const total = hm.segments.reduce((a: number, s: any) => a + (hm.timed && s.end != null ? Math.max(0.5, s.end - s.start) : 1), 0);
  const s = hm.segments[sel];
  const lc = r.platforms.length_check || [];
  return (
    <S id="attention" title="Attention, moment by moment" sub="Hold rate per segment from first-exposure reactions, projected over the audience.">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Card className="p-5">
          <div className="flex items-center justify-between text-xs"><span className="text-muted">Completion <b className="num text-fg">{fmt.pct(hm.completion)}</b></span>
            <span className="text-muted">Peak at segment {(hm.peak ?? 0) + 1} · largest drop at segment {(hm.worst ?? 0) + 1}</span></div>
          <div className="mt-3 flex h-12 gap-[2px]">
            {hm.segments.map((g: any, k: number) => {
              const w = hm.timed && g.end != null ? Math.max(0.5, g.end - g.start) : 1;
              return (
                <button key={k} onClick={() => setSel(k)} title={g.label} style={{ flex: `${w / total} 1 0`, background: engColor(g.engagement) }}
                  className={cn("relative flex items-end overflow-hidden px-1.5 pb-1 text-[11px] font-medium text-white", sel === k && "ring-2 ring-fg ring-offset-1 ring-offset-panel")}>
                  <span className="num">{Math.round(g.engagement * 100)}%</span>
                </button>
              );
            })}
          </div>
          <div className="mt-1 flex gap-[2px] text-[11px] text-muted">
            {hm.segments.map((g: any, k: number) => <span key={k} className="num truncate" style={{ flex: `${(hm.timed && g.end != null ? Math.max(0.5, g.end - g.start) : 1) / total} 1 0` }}>{hm.timed ? fmt.t(g.start) : `${k + 1}`}</span>)}
          </div>
          <div className="mt-5 eyebrow mb-1">Still watching</div>
          <LineSimple area height={140} yMax={1} yFmt={(v) => fmt.pct(v)} xFmt={(v) => (hm.timed ? fmt.t(v) : `${v}`)}
            points={[{ x: 0, y: 1 }, ...hm.segments.map((g: any, k: number) => ({ x: hm.timed && g.end != null ? Math.round(g.end) : k + 1, y: g.retention }))]} />
          {lc.length > 0 && <div className="mt-2 text-xs text-muted">If cut short: {lc.map((c: any) => `${c.seconds}s → ${fmt.pct(c.still_watching)} still watching`).join(" · ")}</div>}
        </Card>
        <Card className="p-4">
          {s && (
            <>
              {onComment && <div className="mb-2 flex justify-end"><Button size="sm" variant="ghost" onClick={() => onComment(`segment:${sel}`)}>Comment on this moment</Button></div>}
              <div className="flex items-baseline justify-between"><div className="text-[13px] font-semibold">Segment {sel + 1}: {s.label}</div><span className="num text-2xs text-muted">{hm.timed ? `${fmt.t(s.start)}–${fmt.t(s.end)}` : ""}</span></div>
              <p className="mt-2 text-xs leading-relaxed text-fg/85" dir="auto">{s.text}</p>
              {s.note && <p className="mt-1 text-2xs text-muted">{s.note}</p>}
              <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                <Stat label="Hold" value={fmt.pct(s.engagement, 1)} accent={engColor(s.engagement)} />
                <Stat label="Lost here" value={fmt.pct(s.loss, 1)} />
                <Stat label="Still watching" value={fmt.pct(s.retention, 1)} />
                <Stat label="Stopped here" value={s.drop_votes} sub="voice agents" />
              </div>
              {s.drop_quotes?.map((q: any) => <blockquote key={q.agent} className="mt-3 border-l-2 border-line-strong pl-3 text-xs text-muted">“{q.quote}”<div className="mt-0.5 text-[11px] text-faint">{q.name}</div></blockquote>)}
            </>
          )}
        </Card>
      </div>
      <Card className="mt-4 p-5">
        <div className="mb-3 text-[13px] font-semibold">Who drops where</div>
        <HeatGrid rows={hm.rows} columns={hm.segments.map((x: any) => x.label)} />
      </Card>
    </S>
  );
}

function GroupCard({ title, list, onAgent, tone }: { title: string; list: any[]; onAgent: (r: string) => void; tone: "pos" | "neg" | "warn" }) {
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2"><span className={cn("h-2 w-2 rounded-full", tone === "pos" ? "bg-pos" : tone === "neg" ? "bg-neg" : "bg-warn")} />{title}</span>} />
      <div className="divide-y divide-line px-4 pb-2">
        {list.length === 0 && <div className="py-4 text-xs text-muted">No group stands out here.</div>}
        {list.map((g) => (
          <div key={g.key} className="py-3">
            <div className="flex items-baseline justify-between"><span className="text-[13px] font-medium">{g.label}</span><span className="num text-lg" style={{ color: scoreColor(g.score) }}>{g.score.toFixed(1)}</span></div>
            <div className="text-2xs text-muted">{fmt.pct(g.share_of_audience, 1)} of audience · {g.voice_n} interviewed · share {fmt.pct(g.would_share)}{g.gap ? ` · ${g.gap} below average despite topic interest ×${g.topic_interest}` : ""}</div>
            {g.objection && <div className="mt-1 text-2xs"><span className="text-faint">Objection:</span> {g.objection}</div>}
            {g.evidence && <button onClick={() => onAgent(g.evidence.agent)} className="mt-1.5 block border-l-2 border-line-strong pl-2.5 text-left text-xs text-muted hover:text-fg">“{g.evidence.quote}” <span className="text-[11px] text-faint">· {g.evidence.name}</span></button>}
          </div>
        ))}
      </div>
    </Card>
  );
}

function Audience({ r, sim, onAgent }: { r: any; sim: Simulation; onAgent: (r: string) => void }) {
  const ref = useReference();
  const [f, setF] = useState<any>({ regions: [], genders: [], age_min: "", age_max: "", platforms: [] });
  const ex = useMutation({ mutationFn: () => api(`/simulations/${sim.id}/explore`, { json: { ...f, age_min: f.age_min || null, age_max: f.age_max || null } }) });
  const g = r.groups;
  const toRows = (arr: any[]) => arr.map((x) => ({ label: x.label, value: x.score, sub: fmt.pct(x.share_of_audience) }));
  return (
    <S id="audience" title="Who it lands with" sub="Demographic intersections ranked by projected opinion. Evidence quotes come from interviewed agents in each group.">
      <div className="grid gap-4 lg:grid-cols-3">
        <GroupCard title="Loves it" list={r.winners} onAgent={onAgent} tone="pos" />
        <GroupCard title="Resists it" list={r.losers} onAgent={onAgent} tone="neg" />
        <GroupCard title="Opportunity gaps" list={r.opportunities} onAgent={onAgent} tone="warn" />
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card className="space-y-5 p-5"><div><div className="eyebrow mb-2">By region</div><BarList rows={toRows(g.region)} colorFor={scoreColor} /></div>
          <div><div className="eyebrow mb-2">By gender</div><BarList rows={toRows(g.gender)} colorFor={scoreColor} /></div></Card>
        <Card className="space-y-5 p-5"><div><div className="eyebrow mb-2">By age</div><BarList rows={toRows(g.age)} colorFor={scoreColor} /></div>
          <div><div className="eyebrow mb-2">By disposition</div><BarList rows={toRows(g.stance)} colorFor={scoreColor} /></div></Card>
      </div>
      <Card className="mt-4 p-5">
        <div className="text-[13px] font-semibold">Deep dive into any slice</div>
        <p className="mt-0.5 text-xs text-muted">Query the projected reactions of every agent in a demographic intersection of the 1M population.</p>
        <div className="mt-3 grid grid-cols-2 items-end gap-2 lg:grid-cols-[1.4fr_80px_80px_1fr_1fr_auto]">
          <Field label="Region"><Select value={f.regions[0] || ""} onChange={(v) => setF({ ...f, regions: v === "*" ? [] : [v] })}
            options={[{ value: "*", label: "Any" }, ...(ref.data?.regions || []).filter((x) => (sim.audience?.regions || []).includes(x.code) || !(sim.audience?.regions || []).length).map((x) => ({ value: x.code, label: x.name }))]} /></Field>
          <Field label="Age from"><Input type="number" value={f.age_min} onChange={(e) => setF({ ...f, age_min: e.target.value })} /></Field>
          <Field label="to"><Input type="number" value={f.age_max} onChange={(e) => setF({ ...f, age_max: e.target.value })} /></Field>
          <Field label="Gender"><Select value={f.genders[0] || "*"} onChange={(v) => setF({ ...f, genders: v === "*" ? [] : [v] })} options={[{ value: "*", label: "Any" }, { value: "female", label: "Women" }, { value: "male", label: "Men" }]} /></Field>
          <Field label="Uses platform"><Select value={f.platforms[0] || "*"} onChange={(v) => setF({ ...f, platforms: v === "*" ? [] : [v] })} options={[{ value: "*", label: "Any" }, ...(ref.data?.platforms || []).map((p) => ({ value: p.key, label: p.label }))]} /></Field>
          <Button variant="primary" onClick={() => ex.mutate()} loading={ex.isPending}>Analyse</Button>
        </div>
        {ex.data && (
          ex.data.size === 0 ? <div className="mt-4 text-xs text-muted">No agents in this slice.</div> : (
            <div className="mt-5 grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
              <div>
                <Stat label={`${fmt.n(ex.data.size)} agents · ${fmt.pct(ex.data.share_of_audience, 1)}`} value={ex.data.score.toFixed(2)} accent={scoreColor(ex.data.score)}
                  sub={`share ${fmt.pct(ex.data.would_share, 1)} · ${ex.data.voice_n} interviewed`} />
                <div className="mt-2"><Histogram counts={ex.data.score_hist} mean={ex.data.score} height={70} /></div>
                {ex.data.caveat && <Callout tone="warn" className="mt-2">{ex.data.caveat}</Callout>}
              </div>
              <div><div className="eyebrow mb-2">Still watching</div>
                <div className="flex h-16 items-end gap-0.5">{ex.data.retention.map((v: number, i: number) => <div key={i} className="flex-1 rounded-t-sm" title={`Segment ${i + 1}: ${fmt.pct(v)}`} style={{ height: `${v * 100}%`, background: engColor(ex.data.engagement[i]) }} />)}</div>
                <div className="eyebrow mb-1 mt-4">Values</div>
                {Object.entries(ex.data.attitudes).map(([k, v]: any) => <div key={k} className="grid grid-cols-[110px_1fr] items-center gap-2 text-2xs"><span className="capitalize text-muted">{k.replace("_", " ")}</span><Bar value={v} /></div>)}
              </div>
              <div>{ex.data.recommendations?.length > 0 && <><div className="eyebrow mb-2">How to reach them</div>
                <ul className="mb-3 space-y-1 text-xs leading-relaxed">{ex.data.recommendations.map((t: string, i: number) => <li key={i} className="flex gap-1.5"><span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-faint" />{t}</li>)}</ul></>}
                <div className="eyebrow mb-2">Interests</div>
                {ex.data.interests.map((i: any) => <div key={i.label} className="flex justify-between text-xs"><span className="text-muted">{i.label}</span><span className="num">{fmt.pct(i.w)}</span></div>)}
                <div className="eyebrow mb-1 mt-3">Platforms</div>
                {ex.data.platforms.slice(0, 4).map((p: any) => <div key={platformName(p.platform)} className="flex justify-between text-xs"><span className="text-muted">{platformName(p.platform)}</span><span className="num">{fmt.pct(p.share)}</span></div>)}
              </div>
              <div><div className="eyebrow mb-2">In their words</div>
                {ex.data.quotes.slice(0, 4).map((q: any) => <button key={q.agent} onClick={() => onAgent(q.agent)} className="mb-2 block border-l-2 border-line-strong pl-2.5 text-left text-xs text-muted hover:text-fg">“{q.quote}”<div className="text-[11px] text-faint">{q.who} · {fmt.s1(q.score)}</div></button>)}
                {ex.data.quotes.length === 0 && <div className="text-xs text-muted">No interviewed agents in this slice.</div>}
              </div>
            </div>
          )
        )}
      </Card>
    </S>
  );
}

function Dynamics({ r, onAgent }: { r: any; onAgent: (r: string) => void }) {
  const d = r.discourse;
  const acts = Object.entries(d.actions).sort((a: any, b: any) => b[1] - a[1]);
  return (
    <S id="dynamics" title="How the conversation unfolded" sub="What the simulated agents did on the feed and the forum, who led the conversation and which posts took off.">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card className="p-4"><Stat label="Posts created" value={fmt.n(d.posts)} /></Card>
        <Card className="p-4"><Stat label="Changed their mind" value={d.changed_mind} sub="interviewed agents moving 1+ point" /></Card>
        <Card className="p-4"><Stat label="Mean shift" value={(d.mean_shift >= 0 ? "+" : "") + d.mean_shift.toFixed(2)} accent={d.mean_shift >= 0 ? "rgb(var(--pos))" : "rgb(var(--neg))"} /></Card>
        <Card className="p-4"><Stat label="Polarisation" value={`${d.polarization_before} → ${d.polarization_after}`} sub="std dev of opinions" /></Card>
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_320px]">
        <Card>
          <CardHeader title="Top posts" subtitle="Ranked by likes, reposts and comments (agents + crowd)" />
          <div className="divide-y divide-line px-4 pb-2">
            {d.top_posts.slice(0, 6).map((p: any) => (
              <div key={p.id} className="py-2.5">
                <div className="flex items-center gap-1.5 text-2xs text-muted"><Badge tone="outline">{platformName(p.platform)}</Badge><Badge tone="outline">{p.kind}</Badge>
                  <button onClick={() => p.author_ref?.includes(":") && onAgent(p.author_ref)} className="truncate hover:text-fg">{p.author}</button><span className="ml-auto">R{p.round}</span></div>
                <div dir="auto" className="mt-1 text-xs leading-relaxed">{p.content}</div>
                <div className="num mt-1 text-[11px] text-muted">{fmt.n(p.likes + p.crowd_likes + p.up)} likes · {fmt.n(p.reposts + p.crowd_reposts)} reposts · {fmt.n(p.comments)} comments{p.down ? ` · ${p.down} downvotes` : ""} · {fmt.k(p.views)} views</div>
              </div>
            ))}
          </div>
        </Card>
        <Card>
          <CardHeader title="Opinion leaders" subtitle="Agents whose posts drew the most engagement" />
          <div className="divide-y divide-line px-4 pb-2">
            {d.leaders.map((l: any) => (
              <button key={l.agent} onClick={() => onAgent(l.agent)} className="flex w-full items-center gap-2.5 py-2 text-left hover:opacity-80">
                <span className="h-2 w-2 rounded-full" style={{ background: STANCE_COLORS[l.stance] || "#94a3b8" }} />
                <span className="min-w-0 flex-1"><span className="block truncate text-xs font-medium">{l.name} <span className="font-normal text-muted">@{l.handle}</span></span>
                  <span className="block text-xs capitalize text-muted">{l.kind} · {l.region} · {fmt.n(l.followers)} followers</span></span>
                <span className="num text-xs">{fmt.k(l.engagement)}</span>
                <span className="num w-8 text-right text-xs" style={{ color: scoreColor(l.opinion) }}>{fmt.s1(l.opinion)}</span>
              </button>
            ))}
          </div>
        </Card>
        <Card className="p-4">
          <div className="eyebrow mb-2">Actions</div>
          <div className="space-y-1">{acts.slice(0, 14).map(([k, v]: any) => <div key={k} className="flex justify-between text-xs"><span className="text-muted">{k.replace(":", " · ")}</span><span className="num">{fmt.n(v)}</span></div>)}</div>
          <div className="eyebrow mb-2 mt-4">Shift by disposition</div>
          {Object.entries(d.shift_by_stance).map(([k, v]: any) => <div key={k} className="flex justify-between text-xs"><span className="capitalize text-muted">{k}</span><span className={cn("num", v >= 0 ? "text-pos" : "text-neg")}>{v >= 0 ? "+" : ""}{v}</span></div>)}
        </Card>
      </div>
      {r.timeline?.length > 1 && <Card className="mt-4 p-5"><div className="eyebrow mb-2">Views of the creator's post by round</div><ReachChart data={r.timeline} height={160} /></Card>}
    </S>
  );
}

function Spread({ r }: { r: any }) {
  const c = r.viral.cascade;
  const max = Math.max(...c.region_reach.map((x: any) => x.n), 1);
  return (
    <S id="spread" title="How far it spreads" sub={r.viral.method}>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Card className="p-5">
          <div className="eyebrow mb-2">Agents reached per share step (median of {c.runs} runs on the 1M follower graph)</div>
          <LineSimple area height={200} points={c.curve.map((x: any) => ({ x: x.step, y: x.exposed }))} yFmt={(v) => fmt.k(v)} xFmt={(v) => `step ${v}`} />
        </Card>
        <Card className="space-y-3 p-5">
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Median reach" value={fmt.k(c.reach_median)} sub={`from ${fmt.n(c.seeds)} seeds`} />
            <Stat label="Amplification" value={`×${c.amplification_median}`} sub={`P(>2×) ${fmt.pct(c.p_amplification_over_2x)}`} />
            <Stat label="10–90th pct" value={`${fmt.k(c.reach_p10)}–${fmt.k(c.reach_p90)}`} />
            <Stat label="Outside audience" value={fmt.pct(c.outside_audience_share)} sub={`sim boost ×${c.boost}`} />
          </div>
          <div className="pt-2">{c.region_reach.map((x: any) => (
            <div key={x.code} className="grid grid-cols-[110px_1fr_44px] items-center gap-2 text-xs"><span className="text-muted">{x.name}</span><Bar value={x.n} max={max} color={REGION_COLORS[x.code]} /><span className="num text-right">{fmt.k(x.n)}</span></div>
          ))}</div>
          {c.real_world && <KV className="border-t border-line pt-1" rows={[["Rough real-world reach", `${fmt.k(c.real_world.p10)}–${fmt.k(c.real_world.p90)} people`],
            ["Chance of 100k+ people", fmt.pct(c.real_world.p_over_100k)], ["Chance of 1M+ people", fmt.pct(c.real_world.p_over_1m)]]} />}
          <p className="text-xs text-faint">Assumptions: feed visibility {fmt.pct(c.assumptions.feed_visibility)}, intent to action {fmt.pct(c.assumptions.intent_to_action)}. {c.real_world?.method}</p>
        </Card>
      </div>
    </S>
  );
}

function Platforms({ r }: { r: any }) {
  const pl = r.platforms.by_platform;
  return (
    <S id="platforms" title="Platform fit" sub="Projected reactions of audience agents who use each platform weekly.">
      <Card className="overflow-x-auto">
        <table className="dt min-w-[640px]">
          <thead><tr><th>Platform</th><th className="!text-right">Audience share</th><th>Opinion among its users</th><th className="!text-right">Share intent</th><th className="!text-right">Completion</th></tr></thead>
          <tbody>{pl.map((p: any) => (
            <tr key={platformName(p.platform)}>
              <td className="font-medium">{p.label}{p.platform === r.platforms.target && <span className="ml-2 text-xs font-normal text-brand">Target platform</span>}</td>
              <td className="r">{fmt.pct(p.reach_share)}</td>
              <td><div className="flex items-center gap-2"><Bar value={p.score} max={10} color={scoreColor(p.score)} className="max-w-[220px]" /><span className="num">{p.score.toFixed(2)}</span></div></td>
              <td className="r">{fmt.pct(p.would_share, 1)}</td><td className="r">{fmt.pct(p.completion)}</td>
            </tr>))}</tbody>
        </table>
      </Card>
    </S>
  );
}

function Psychology({ r }: { r: any }) {
  const p = r.psychology;
  return (
    <S id="psychology" title="Audience psychology" sub={`From ${r.audience.voice_n} interviewed agents. Emotion bars are coloured by the mean opinion of agents feeling it.`}>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card className="p-4"><div className="eyebrow mb-3">Primary emotion</div><BarList rows={p.emotions.map((e: any) => ({ label: e.emotion, value: e.share }))} max={Math.max(...p.emotions.map((e: any) => e.share), 0.01)} valueFmt={(v) => fmt.pct(v)} colorFor={(v) => { const e = p.emotions.find((x: any) => x.share === v); return scoreColor(e?.mean_score); }} /></Card>
        <Card className="p-4"><div className="eyebrow mb-3">Drivers</div><BarList rows={p.drivers.map((e: any) => ({ label: e.driver, value: e.share }))} max={Math.max(...p.drivers.map((e: any) => e.share), 0.01)} valueFmt={(v) => fmt.pct(v)} colorFor={() => SERIES.d} /></Card>
        <Card className="p-4"><div className="eyebrow mb-3">Decision mode</div><BarList rows={p.decision_modes.map((e: any) => ({ label: e.mode, value: e.share }))} max={1} valueFmt={(v) => fmt.pct(v)} colorFor={() => SERIES.a} /></Card>
        <Card className="p-4"><div className="eyebrow mb-3">Top objections</div>
          {p.objections.length === 0 ? <div className="text-xs text-muted">None</div> : p.objections.map((o: any) => <div key={o.objection} className="flex justify-between border-b border-line py-1.5 text-xs last:border-0"><span>{o.objection}</span><span className="num text-muted">{o.n}</span></div>)}</Card>
      </div>
    </S>
  );
}

function AB({ r }: { r: any }) {
  const ab = r.ab;
  const them = ab.kind === "competitor";
  const name = (k: string) => (them ? (k === "A" ? "Your content" : "Competitor") : `Version ${k}`);
  const banner = ab.winner === "tie" ? "No clear difference" : `${name(ab.winner)} ${them ? "is preferred" : "is preferred"}`;
  return (
    <S id="ab" title={ab.kind === "competitor" ? "Competitor benchmark" : "A/B comparison"} sub={ab.method}>
      <div className="grid gap-4 lg:grid-cols-3">
        {(["a", "b"] as const).map((k) => (
          <Card key={k} className="p-5">
            <Badge tone={ab.winner === k.toUpperCase() ? "pos" : "default"}>{name(k.toUpperCase())}</Badge>
            <div className="num mt-3 flex items-center gap-2 text-3xl font-semibold"><span className="h-3 w-3 rounded-[2px]" style={{ background: scoreColor(ab[k].score) }} aria-hidden />{ab[k].score.toFixed(2)}</div>
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs"><Stat label="Share intent" value={fmt.pct(ab[k].would_share, 1)} /><Stat label="Completion" value={fmt.pct(ab[k].completion)} /></div>
          </Card>
        ))}
        <Card className="p-5">
          <div className="text-lg font-semibold">{banner}</div>
          <p className="mt-2 text-xs text-muted">Same {ab.paired_n} agents saw both. Mean paired difference (B − A): <b className="num text-fg">{ab.mean_diff >= 0 ? "+" : ""}{ab.mean_diff.toFixed(2)}</b> (95% {ab.diff_low.toFixed(2)} to {ab.diff_high.toFixed(2)}).</p>
          <p className="mt-2 text-xs text-muted">Probability {them ? "the competitor" : "B"} is better: <b className="num text-fg">{fmt.pct(ab.p_b_better)}</b></p>
        </Card>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card className="p-4"><div className="eyebrow mb-3">By region</div><Dumbbell rows={ab.by_region} /></Card>
        <Card className="p-4"><div className="eyebrow mb-3">By age</div><Dumbbell rows={ab.by_age} /></Card>
        <Card className="p-4"><div className="eyebrow mb-3">By disposition</div><Dumbbell rows={ab.by_stance} /></Card>
      </div>
    </S>
  );
}

function Population({ r, onAgent }: { r: any; onAgent: (ref: string) => void }) {
  const [c, setC] = useState<"score" | "region" | "stance">("score");
  return (
    <S id="population" title="Population lens" sub={`${fmt.n(r.population_sample.rows.length)} agents sampled from the audience by age and projected opinion. Click any dot to open that agent and interview it.`}>
      <Card className="p-4">
        <div className="mb-2 flex justify-end"><Segmented value={c} onChange={setC} options={[{ value: "score", label: "Opinion" }, { value: "region", label: "Region" }, { value: "stance", label: "Stance" }]} /></div>
        <PopulationScatter sample={r.population_sample} colorBy={c} onPick={(id) => onAgent(`p:${id}`)} />
        <p className="mt-2 text-2xs text-faint">Reaction surface fit (R²): score {r.model.r2.score}, share {r.model.r2.would_share}. The rest is kept as individual variation.</p>
      </Card>
    </S>
  );
}

function Context({ sim, r }: { sim: Simulation; r: any }) {
  const ctx = sim.config?.context || {};
  const ck = r.checks;
  return (
    <S id="context" title="World context and checks" sub={r.trend.method}>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_340px]">
        <Card className="p-4">
          <div className="eyebrow mb-2">Trend alignment {fmt.pct(r.trend.score)}</div>
          {r.trend.matches.length === 0 ? <div className="text-xs text-muted">No overlap with what the audience's regions were reading at publish time.</div>
            : r.trend.matches.slice(0, 8).map((m: any, i: number) => <div key={i} className="border-b border-line py-1.5 text-xs last:border-0"><span className="font-medium">{m.region} · {m.kind}</span> <span dir="auto">{m.title}</span><div className="text-[11px] text-faint">Shared terms: {m.overlap.join(", ")}</div></div>)}
        </Card>
        <Card className="p-4">
          <div className="eyebrow mb-2">Regional briefs</div>
          {Object.entries(ctx).map(([k, c]: any) => <div key={k} className="mb-2 text-xs"><b>{c.city}</b> <span dir="auto" className="text-muted">{c.brief}</span></div>)}
        </Card>
        <Card className="space-y-2 p-4 text-xs">
          <div className="eyebrow">Pre-flight checks</div>
          <div className="flex justify-between"><span className="text-muted">Hook strength</span><span className="num">{fmt.pct(ck.hook?.strength)}</span></div>
          <div className="flex justify-between"><span className="text-muted">Readability (Flesch)</span><span className="num">{ck.readability ?? "n/a"}</span></div>
          <div className="flex justify-between"><span className="text-muted">Words</span><span className="num">{fmt.n(ck.word_count)}</span></div>
          {ck.sensitivity_flags?.length > 0 ? <Callout tone="warn" title="Sensitivity flags">{ck.sensitivity_flags.join(" · ")}</Callout> : <div className="text-muted">No sensitivity flags.</div>}
          {ck.claims?.length > 0 && <Callout tone="info" title="Claims a skeptic will test">{ck.claims.join(" · ")}</Callout>}
        </Card>
      </div>
    </S>
  );
}

function Calibrate({ sim }: { sim: Simulation }) {
  const list = useQuery({ queryKey: ["perf", sim.id], queryFn: () => api<any[]>(`/simulations/${sim.id}/performance`) });
  const [f, setF] = useState<any>({ platform: sim.content?.platform || "", views: "", likes: "", shares: "", comments: "", retention: "" });
  const save = useMutation({
    mutationFn: () => api(`/simulations/${sim.id}/performance`, { json: Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v === "" ? null : k === "platform" ? v : Number(v)])) }),
    onSuccess: () => { list.refetch(); toast.success("Saved. It now counts toward calibration."); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });
  return (
    <S id="calibrate" title="Calibrate against reality" sub="After publishing, record what actually happened. Each report becomes ground truth; the Calibration page tracks how well predictions rank real outcomes.">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card className="p-4">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
            {["platform", "views", "likes", "shares", "comments", "retention"].map((k) => (
              <Field key={k} label={k === "retention" ? "Avg % watched" : k[0].toUpperCase() + k.slice(1)}><Input value={f[k]} type={k === "platform" ? "text" : "number"} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></Field>
            ))}
          </div>
          <Button className="mt-3" variant="primary" size="sm" onClick={() => save.mutate()} loading={save.isPending}>Save result</Button>
        </Card>
        <Card className="p-4 text-xs">
          {(list.data || []).length === 0 ? <div className="text-muted">No real-world results reported yet.</div> : (list.data || []).map((p, i) => (
            <div key={i} className="flex justify-between border-b border-line py-1.5 last:border-0"><span>{fmt.date(p.at)} · {platformName(p.platform)}</span><span className="num">{fmt.k(p.views)} views · {p.engagement_rate ?? "–"}%</span></div>
          ))}
        </Card>
      </div>
    </S>
  );
}

function Run({ r, sim }: { r: any; sim: Simulation }) {
  const u = r.usage || {};
  return (
    <S id="run" title="Method and run details">
      <div className="grid gap-4 text-xs lg:grid-cols-3">
        <Card className="space-y-1.5 p-4">
          <div className="eyebrow mb-1">Model usage</div>
          <Row k="Retrieval model" v={r.creator?.retrieval_usage?.model || "local"} />
          <Row k="Embedding cost" v={r.creator?.retrieval_usage?.extra_cost_usd == null ? "Unavailable" : `$${r.creator.retrieval_usage.extra_cost_usd.toFixed(5)}`} />
          <Row k="Provider" v={r.provider?.dry ? "dry run" : `${r.provider?.preset} (${r.provider?.source})`} />
          <Row k="Voice model" v={r.provider?.voice_model || "–"} /><Row k="Report model" v={r.provider?.report_model || "–"} />
          <Row k="Calls (failed)" v={`${fmt.n(u.calls)} (${u.failed})`} /><Row k="Tokens in (cached)" v={`${fmt.n(u.input_tokens)} (${fmt.n(u.cached_tokens)})`} />
          <Row k="Tokens out" v={fmt.n(u.output_tokens)} /><Row k="Cost" v={u.cost_usd != null ? `$${u.cost_usd.toFixed(4)}` : "set prices in provider settings"} />
          <Row k="Credits charged" v={fmt.n((sim as any).credits_charged)} />
        </Card>
        <Card className="space-y-2 p-4 text-muted leading-relaxed">
          <div className="eyebrow mb-1">Method</div>
          <p>{r.score.method}</p>
          {r.agent_memory && <p>Simulated audience memory: {r.agent_memory.returning ?? 0} of {r.agent_memory.voice ?? 0} voice agents were returning; {r.agent_memory.recalled ?? 0} memories recalled.
            {r.agent_memory.fresh ? " Fresh audience was on; history was ignored." : " Fresh audience was off."}
            {!!r.agent_memory.shortfall && ` ${r.agent_memory.shortfall} requested returning places could not be filled within the audience segments.`}</p>}
          {Object.entries(sim.config?.context || {}).map(([code, context]: any) => context.tone && <p key={code}>{context.city || code} news tone: {context.tone.source_label || "GDELT"} · source weight {context.tone.source_weight ?? 1}{context.tone.warning ? `. ${context.tone.warning}.` : ""}</p>)}
          <p>Reaction surface: ridge regression on {r.model.features} persona features (λ={r.model.lambda}) fitted on {r.model.voice_n} interviewed agents, applied to {fmt.n(r.audience.population)} agents.</p>
        </Card>
        <Card className="space-y-1.5 p-4">
          <div className="eyebrow mb-1">Reproduce</div>
          <Row k="Seed" v={r.seed} /><Row k="Runtime" v={`${r.runtime_seconds}s`} /><Row k="Stopped early" v={r.stopped_early ? "yes" : "no"} />
          <Row k="Regions" v={r.audience.regions.map((x: any) => x.code).join(" ")} />
        </Card>
      </div>
    </S>
  );
}

function Row({ k, v }: { k: string; v: any }) {
  return <div className="flex justify-between gap-3"><span className="text-muted">{k}</span><span className="num truncate text-right">{v}</span></div>;
}
