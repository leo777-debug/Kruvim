import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { LineSimple } from "@/components/charts";
import { Button } from "@/components/ui/button";
import { Sheet, SheetClose } from "@/components/ui/overlay";
import { Badge, Bar, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { ACTION_COLORS, engColor, scoreColor, STANCE_COLORS } from "@/lib/colors";
import { fmt, initials, platformName } from "@/lib/utils";

export function AgentSheet({ simId, agentRef, onClose, onChat }: { simId: string; agentRef: string | null; onClose: () => void; onChat?: (ref: string) => void }) {
  const q = useQuery({ queryKey: ["agent", simId, agentRef], queryFn: () => api(`/simulations/${simId}/agents/${agentRef}`), enabled: !!agentRef });
  const d = q.data;
  const p = d?.persona || {};
  const r = d?.reaction || {};
  const st = d?.state || {};
  const score = st.opinion ?? r.score ?? d?.projected?.score;
  return (
    <Sheet open={!!agentRef} onOpenChange={(v) => !v && onClose()} width={540}>
      <div className="flex items-start gap-3 border-b border-line px-5 py-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-raised text-xs font-semibold text-muted"
          style={{ boxShadow: score != null ? `0 0 0 2px ${scoreColor(score)}` : undefined }}>{initials(d?.name)}</div>
        <div className="min-w-0 flex-1">
          {q.isLoading ? <Skeleton className="h-5 w-40" /> : (
            <>
              <div className="flex items-center gap-2"><span className="truncate text-sm font-semibold">{d?.name}</span><span className="text-xs text-muted">@{d?.handle}</span></div>
              <div className="mt-1 flex flex-wrap gap-1">
                <Badge tone="outline">{d?.kind === "voice" ? "Voice agent" : d?.kind === "population" ? "Population agent" : "Stakeholder account"}</Badge>
                {p.stance && <Badge><span className="h-1.5 w-1.5 rounded-full" style={{ background: STANCE_COLORS[p.stance] }} />{p.stance}</Badge>}
                {d?.in_audience === false && <Badge tone="warn">Outside audience</Badge>}
                <Badge tone="outline">{fmt.n(d?.followers)} followers</Badge>
              </div>
            </>
          )}
        </div>
        {score != null && <div className="text-right"><div className="num text-lg font-semibold leading-tight" style={{ color: scoreColor(score) }}>{fmt.s1(score)}</div><div className="text-[11px] text-muted">opinion</div></div>}
        <SheetClose className="rounded p-1 text-muted hover:bg-raised hover:text-fg"><X className="h-4 w-4" /></SheetClose>
      </div>
      <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4 text-[13px]">
        {d && (
          <>
            <section>
              <div className="eyebrow mb-2">Who they are</div>
              {d.kind === "stakeholder" ? <p className="text-muted leading-relaxed">{p.description}</p> : (
                <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
                  <Kv k="Age / gender" v={`${p.age} · ${p.gender}`} /><Kv k="Origin" v={p.origin} />
                  <Kv k="City" v={`${p.city}, ${p.region_name ?? ""}`} /><Kv k="Language" v={p.language} />
                  <Kv k="Work" v={p.profession} /><Kv k="Education" v={p.education} />
                  <Kv k="Income" v={p.income} /><Kv k="Screen time" v={p.screen_time} />
                  <Kv k="Platforms" v={(p.platforms || []).join(", ")} /><Kv k="Interests" v={(p.interests || []).map((i: any) => i.label).join(", ")} />
                </div>
              )}
            </section>
            {p.ocean && (
              <section className="grid grid-cols-2 gap-6">
                <div>
                  <div className="eyebrow mb-2">Personality</div>
                  {Object.entries(p.ocean).map(([k, v]: any) => <Trait key={k} k={k} v={v} />)}
                </div>
                <div>
                  <div className="eyebrow mb-2">Values</div>
                  {Object.entries(p.attitudes || {}).map(([k, v]: any) => <Trait key={k} k={k.replace("_", " ")} v={v} />)}
                </div>
              </section>
            )}
            {r.score != null && (
              <section>
                <div className="eyebrow mb-2">First reaction</div>
                {r.quote && <blockquote className="border-l-2 border-line-strong pl-3 text-[14px] text-fg">“{r.quote}”</blockquote>}
                <p className="mt-2 text-xs text-muted">{r.reason}</p>
                <div className="mt-3 grid grid-cols-3 gap-3 text-xs">
                  <Kv k="Emotion" v={`${r.primary_emotion} (${fmt.pct(r.emotion_intensity)})`} />
                  <Kv k="Share / comment" v={`${fmt.pct(r.would_share)} / ${fmt.pct(r.would_comment)}`} />
                  <Kv k="Stops at" v={r.drop_segment ? `segment ${r.drop_segment}` : "watches to the end"} />
                  <Kv k="Drivers" v={(r.drivers || []).join(", ") || "–"} />
                  <Kv k="Objection" v={r.objection || "–"} />
                  <Kv k="Mode" v={r.decision_mode || "–"} />
                </div>
                {r.segment_engagement && (
                  <div className="mt-3 flex h-8 items-end gap-0.5">
                    {(() => { let att = 1; return r.segment_engagement.map((e: number, i: number) => { att *= e; return <div key={i} title={`Segment ${i + 1}: ${fmt.pct(att)} still watching`} className="flex-1 rounded-t-sm" style={{ height: `${Math.max(6, att * 100)}%`, background: engColor(e) }} />; }); })()}
                  </div>
                )}
              </section>
            )}
            {d.projected && !r.score && (
              <section>
                <div className="eyebrow mb-2">Projected reaction</div>
                <p className="text-xs text-muted">This agent was not interviewed. Its reaction is projected from the reaction surface fitted on the voice agents,
                  with the spread they showed. Ask it a question and the model answers in character, consistent with this projection.</p>
                <div className="mt-2 grid grid-cols-3 gap-3 text-xs"><Kv k="Score" v={fmt.s1(d.projected.score)} /><Kv k="Share" v={fmt.pct(d.projected.would_share)} /><Kv k="Comment" v={fmt.pct(d.projected.would_comment)} /></div>
              </section>
            )}
            {st.trajectory?.length > 1 && (
              <section>
                <div className="eyebrow mb-1">Opinion over the simulation</div>
                <LineSimple points={st.trajectory.map(([x, y]: number[]) => ({ x, y }))} yMax={10} height={120} xFmt={(v) => `R${v}`} color={scoreColor(st.opinion)} />
              </section>
            )}
            {d.posts?.length > 0 && (
              <section>
                <div className="eyebrow mb-2">What they posted</div>
                <div className="space-y-2">
                  {d.posts.filter((x: any) => x.content).slice(-8).map((x: any) => (
                    <div key={x.id} className="rounded-md border border-line px-3 py-2">
                      <div className="mb-1 flex gap-1.5 text-xs text-muted"><span>{platformName(x.platform)} · {x.kind} · round {x.round}</span>
                        <span className="num ml-auto">{(x.stats?.likes || 0) + (x.stats?.crowd_likes || 0) + (x.stats?.up || 0)} likes · {(x.stats?.reposts || 0) + (x.stats?.crowd_reposts || 0)} reposts</span></div>
                      <div className="text-xs leading-relaxed">{x.content}</div>
                    </div>
                  ))}
                </div>
              </section>
            )}
            {d.actions?.length > 0 && (
              <section>
                <div className="eyebrow mb-2">Activity</div>
                <div className="space-y-1">
                  {d.actions.slice(-20).map((a: any, i: number) => (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <span className="num w-8 text-faint">R{a.round}</span>
                      <span className="w-20 shrink-0 font-medium" style={{ color: ACTION_COLORS[a.action] }}>{a.action.charAt(0) + a.action.slice(1).toLowerCase().replace("_", " ")}</span>
                      <span className="truncate text-muted">{a.content || (a.target_post ? `post #${a.target_post}` : a.target_ref || "")}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>
      {d && onChat && (
        <div className="border-t border-line px-5 py-3">
          <Button variant="primary" className="w-full" onClick={() => onChat(agentRef!)}>Interview this agent</Button>
        </div>
      )}
    </Sheet>
  );
}

function Kv({ k, v }: { k: string; v: any }) {
  return <div className="min-w-0"><div className="text-xs text-muted">{k}</div><div className="truncate text-fg" title={String(v ?? "")}>{v ?? "–"}</div></div>;
}

function Trait({ k, v }: { k: string; v: number }) {
  return (
    <div className="mb-1.5 grid grid-cols-[120px_1fr_34px] items-center gap-2 text-xs">
      <span className="capitalize text-muted">{k}</span><Bar value={v} /><span className="num text-right">{v.toFixed(2)}</span>
    </div>
  );
}
