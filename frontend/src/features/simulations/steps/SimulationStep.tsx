import { FastForward, Heart, MessageCircle, Pause, Play, Quote, Repeat2, Square, ThumbsDown, ThumbsUp, UserPlus, Zap } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { ActivityChart, OpinionTimeline } from "@/components/charts";
import type { GraphHandle } from "@/components/graph/LiveGraph";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/overlay";
import { Callout, Progress, Segmented, Stat, Textarea } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { ACTION_COLORS, REGION_COLORS, scoreColor } from "@/lib/colors";
import type { Simulation } from "@/lib/types";
import { cn, fmt } from "@/lib/utils";
import type { FeedItem, StreamState } from "../useSimulationStream";

const ICON: Record<string, any> = { LIKE: Heart, COMMENT: MessageCircle, REPOST: Repeat2, QUOTE: Quote, FOLLOW: UserPlus, UPVOTE: ThumbsUp, DOWNVOTE: ThumbsDown, POST: Zap };

export function SimulationStep({ sim, stream, refetch, onAgent }: { sim: Simulation; stream: StreamState; refetch: () => void; onAgent: (r: string) => void; graphRef: React.RefObject<GraphHandle> }) {
  const [inject, setInject] = useState(false);
  const [text, setText] = useState("");
  const [view, setView] = useState<"split" | "feed" | "forum">("split");
  const running = ["running", "paused", "queued"].includes(sim.status);
  const st = stream.status || sim.status;
  const round: { round: number; rounds: number; clocks?: Record<string, string> } | null =
    stream.round || (sim.progress?.round != null ? { round: sim.progress.round, rounds: sim.progress.rounds } : null);
  const tl = stream.timeline.length ? stream.timeline : sim.results?.timeline || [];
  const last = tl[tl.length - 1];

  async function control(cmd: string, extra: any = {}) {
    try {
      await api(`/simulations/${sim.id}/control`, { json: { cmd, ...extra } });
      if (cmd === "inject") toast.success("Event injected. Agents will see it next round.");
      refetch();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Failed");
    }
  }

  const feed = useMemo(() => stream.feed.slice().reverse(), [stream.feed.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const left = feed.filter((f) => f.platform === "feed" || f.platform === "both");
  const right = feed.filter((f) => f.platform === "forum" || f.platform === "both");
  const totals = useMemo(() => {
    const a = last?.actions || {};
    const sum = (p: string) => Object.entries(a).filter(([k]) => k.startsWith(p)).reduce((s, [, v]) => s + (v as number), 0);
    return { feed: sum("feed:"), forum: sum("forum:") };
  }, [last]);

  return (
    <div className="flex h-full flex-col bg-panel">
      <div className="border-b border-line px-5 py-4">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className={cn("h-2 w-2 rounded-[2px]", st === "running" ? "animate-pulse2 bg-brand" : st === "completed" ? "bg-pos" : st === "paused" ? "bg-warn" : "bg-faint")} />
            <span className="text-[13px] font-medium capitalize">{st === "queued" ? "Queued, waiting for a worker" : st}</span>
            {round && <span className="num text-xs text-muted">round {round.round}/{round.rounds}</span>}
          </div>
          {running && (
            <div className="flex items-center gap-1.5">
              {st === "paused" ? <Button size="sm" onClick={() => control("resume")}><Play className="h-3.5 w-3.5" />Resume</Button>
                : <Button size="sm" onClick={() => control("pause")}><Pause className="h-3.5 w-3.5" />Pause</Button>}
              <Button size="sm" onClick={() => setInject(true)}>Inject event</Button>
              <Button size="sm" variant="ghost" onClick={() => control("speed", { value: 4 })} title="Fast-forward pacing"><FastForward className="h-3.5 w-3.5" /></Button>
              <Button size="sm" variant="danger" onClick={() => { if (confirm("Stop the simulation and analyse what has happened so far?")) control("stop"); }}><Square className="h-3.5 w-3.5" />Stop</Button>
            </div>
          )}
        </div>
        {round && <Progress className="mt-3" value={round.rounds ? round.round / round.rounds : 0} tone={st === "paused" ? "warn" : "brand"} />}
        {round?.clocks && (
          <div className="mt-2.5 flex flex-wrap gap-x-3 gap-y-1">
            {Object.entries(round.clocks).map(([c, t]) => (
              <span key={c} className="num flex items-center gap-1.5 text-xs text-muted"><span className="h-2 w-2 rounded-[2px]" style={{ background: REGION_COLORS[c] }} />{c} {t}</span>
            ))}
          </div>
        )}
        <div className="mt-4 grid grid-cols-2 gap-4 rounded-md border border-line p-3 2xl:grid-cols-4">
          <Stat label="Voice opinion" value={fmt.s2(last?.voice_opinion)} accent={scoreColor(last?.voice_opinion)} sub={stream.reactionProgress ? `${stream.reactionProgress[0]}/${stream.reactionProgress[1]} reacted` : undefined} />
          <Stat label="Crowd opinion" value={fmt.s2(last?.crowd_opinion)} accent={scoreColor(last?.crowd_opinion)} sub={`${fmt.n(sim.config?.agents?.crowd)} agents`} />
          <Stat label="Post views" value={fmt.k(last?.creator_views)} sub={`${fmt.n(last?.posts)} posts total`} />
          <Stat label="Actions" value={fmt.k(totals.feed + totals.forum)} sub={`feed ${fmt.k(totals.feed)} · forum ${fmt.k(totals.forum)}`} />
        </div>
        {sim.status === "failed" && sim.error && <Callout tone="neg" className="mt-3">{sim.error}</Callout>}
      </div>

      {tl.length > 1 && (
        <div className="grid grid-cols-2 gap-4 border-b border-line px-5 py-3">
          <div><div className="mb-1 text-xs font-medium text-muted">Opinion by round</div><OpinionTimeline data={tl} height={150} /></div>
          <div><div className="mb-1 text-xs font-medium text-muted">Actions per round</div><ActivityChart data={tl} height={150} /></div>
        </div>
      )}

      <div className="flex items-center justify-between px-5 pt-3">
        <h3 className="section-title">Activity log</h3>
        <Segmented value={view} onChange={setView} options={[{ value: "split", label: "Both" }, { value: "feed", label: "Feed" }, { value: "forum", label: "Forum" }]} />
      </div>
      <div className={cn("grid min-h-[420px] flex-1 gap-3 px-5 py-3", view === "split" ? "grid-cols-2" : "grid-cols-1")}>
        {view !== "forum" && <Column title="Feed" items={left} onAgent={onAgent} />}
        {view !== "feed" && <Column title="Forum" items={right} onAgent={onAgent} />}
      </div>

      <Dialog open={inject} onOpenChange={setInject} title="Inject an event"
        description="All agents see it as breaking news from the next round. Use it to test a rebuttal, a controversy, a competitor launch or a news story."
        footer={<><Button onClick={() => setInject(false)}>Cancel</Button><Button variant="primary" disabled={!text.trim()} onClick={() => { control("inject", { text }); setInject(false); setText(""); }}>Inject</Button></>}>
        <Textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. A popular Saudi influencer posts a video calling the ad out of touch" />
      </Dialog>
    </div>
  );
}

function Column({ title, items, onAgent }: { title: string; items: FeedItem[]; onAgent: (r: string) => void }) {
  return (
    <div className="flex min-h-0 flex-col rounded-md border border-line bg-panel">
      <div className="flex items-center justify-between border-b border-line bg-raised px-3 py-2"><span className="text-xs font-medium">{title}</span><span className="num text-xs text-muted">{fmt.n(items.length)} items</span></div>
      <div className="max-h-[560px] flex-1 space-y-0 overflow-y-auto">
        {items.length === 0 && <div className="p-6 text-center text-[13px] text-muted">No activity yet.</div>}
        {items.slice(0, 300).map((f) => <Row key={f.key} f={f} onAgent={onAgent} />)}
      </div>
    </div>
  );
}

function Row({ f, onAgent }: { f: FeedItem; onAgent: (r: string) => void }) {
  if (f.kind === "event") {
    return (
      <div className="border-b border-l-2 border-line border-l-neg bg-neg/[0.04] px-3 py-2.5 animate-fade-in">
        <div className="mb-0.5 flex items-center gap-1.5 text-xs"><span className="font-medium text-neg">Event</span><span className="text-muted">round {f.round} · {f.extra?.source}</span></div>
        <div className="text-[13px] leading-relaxed">{f.content}</div>
      </div>
    );
  }
  const Icon = f.action ? ICON[f.action] || Zap : MessageCircle;
  const color = f.kind === "reaction" ? scoreColor(f.score) : ACTION_COLORS[f.action || ""] || "#94a3b8";
  return (
    <button onClick={() => f.agent && onAgent(f.agent)} className="block w-full border-b border-line px-3 py-2.5 text-left transition-colors hover:bg-raised/60 animate-fade-in">
      <div className="flex items-center gap-1.5 text-xs">
        <span className="h-2 w-2 shrink-0 rounded-[2px]" style={{ background: REGION_COLORS[f.region || "*"] }} />
        <span className="max-w-[45%] truncate font-medium">{f.name || f.agent}</span>
        {f.agentKind === "stakeholder" && <span className="text-muted">account</span>}
        <span className="ml-auto flex items-center gap-1 font-medium" style={{ color }}>
          <Icon className="h-3 w-3" />{f.kind === "reaction" ? `First reaction ${fmt.s1(f.score)}` : (f.action || "").charAt(0) + (f.action || "").slice(1).toLowerCase()}
        </span>
        <span className="num w-12 text-right text-faint">{f.time ?? `R${f.round}`}</span>
      </div>
      {f.content && <div dir="auto" className="mt-1 text-[13px] leading-relaxed text-fg">{f.content}</div>}
      {f.kind === "reaction" && f.extra && (
        <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted">
          <span className="capitalize">{f.extra.sentiment}{f.extra.primary_emotion ? `, ${f.extra.primary_emotion}` : ""}</span>
          <span>Would share <span className="num text-fg">{fmt.pct(f.extra.would_share)}</span></span>
          {f.extra.influence != null && <span>Influence <span className="num text-fg">{fmt.pct(f.extra.influence)}</span></span>}
          {f.extra.drop_segment && <span>Stops at part {f.extra.drop_segment}</span>}
        </div>
      )}
      {!f.content && f.target != null && <div className="mt-0.5 text-xs text-muted">on post #{f.target}</div>}
    </button>
  );
}
