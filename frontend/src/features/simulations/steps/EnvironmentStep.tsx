import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Play, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Callout, Field, Input, KV, Progress, Segmented, Slider, Switch } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { REGION_COLORS, STANCE_COLORS } from "@/lib/colors";
import type { Simulation } from "@/lib/types";
import { fmt } from "@/lib/utils";
import type { StreamState } from "../useSimulationStream";
import { Section } from "./GraphStep";

const DEFAULTS = { voice: 80, crowd: 3000, stakeholders: 5, hours: 24, minutes_per_round: 60, platforms: ["feed", "forum"], listening: true };

export function EnvironmentStep({ sim, stream, onNext, refetch, onAgent }: { sim: Simulation; stream: StreamState; onNext: () => void; refetch: () => void; onAgent: (r: string) => void }) {
  const [o, setO] = useState<any>({ ...DEFAULTS, ...(sim.config?.overrides || {}) });
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState<"all" | "voice" | "stakeholder">("all");
  const preparing = sim.status === "preparing";
  const ready = !!sim.config?.agents && ["ready", "completed", "failed", "cancelled"].includes(sim.status);
  const agents = useQuery({ queryKey: ["agents", sim.id, sim.status], queryFn: () => api<any[]>(`/simulations/${sim.id}/agents`), enabled: ready });
  const cfg = sim.config || {};
  const [plat, setPlat] = useState<any>(cfg.platforms || {});
  const [events, setEvents] = useState<any[]>(cfg.events?.scheduled || []);
  useEffect(() => { setPlat(cfg.platforms || {}); setEvents(cfg.events?.scheduled || []); }, [sim.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps

  async function prepare() {
    setBusy(true);
    try {
      await api(`/simulations/${sim.id}`, { method: "PATCH", json: { overrides: o } });
      await api(`/simulations/${sim.id}/environment`, { method: "POST" });
      refetch();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Failed");
    } finally { setBusy(false); }
  }

  async function saveConfig() {
    await api(`/simulations/${sim.id}/config`, { method: "PATCH", json: { platforms: plat, events: { scheduled: events } } });
    refetch();
    toast.success("Configuration saved");
  }

  async function start() {
    setBusy(true);
    try {
      if (sim.status === "ready") await api(`/simulations/${sim.id}/config`, { method: "PATCH", json: { platforms: plat, events: { scheduled: events } } });
      await api(`/simulations/${sim.id}/start`, { method: "POST" });
      refetch();
      onNext();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not start");
    } finally { setBusy(false); }
  }

  const rounds = Math.max(1, Math.round((o.hours * 60) / o.minutes_per_round));
  const list = (agents.data || []).filter((a) => filter === "all" || a.kind === filter);

  return (
    <div className="bg-panel">
      <Section title="Simulation depth">
        <div className="grid grid-cols-2 gap-x-5 gap-y-4">
          <Field label="Voice agents (language model)" hint={<span className="num">{o.voice}</span>}><Slider value={o.voice} min={10} max={500} step={10} onChange={(v) => setO({ ...o, voice: v })} /></Field>
          <Field label="Crowd agents (statistical)" hint={<span className="num">{fmt.n(o.crowd)}</span>}><Slider value={o.crowd} min={0} max={50000} step={500} onChange={(v) => setO({ ...o, crowd: v })} /></Field>
          <Field label="Stakeholder accounts" hint={<span className="num">{o.stakeholders}</span>}><Slider value={o.stakeholders} min={0} max={15} onChange={(v) => setO({ ...o, stakeholders: v })} /></Field>
          <Field label="Simulated hours" hint={<span className="num">{o.hours}h · {rounds} rounds</span>}><Slider value={o.hours} min={2} max={168} step={2} onChange={(v) => setO({ ...o, hours: v })} /></Field>
          <Field label="Minutes per round">
            <Segmented size="md" value={String(o.minutes_per_round)} onChange={(v) => setO({ ...o, minutes_per_round: Number(v) })} options={["30", "60", "120"].map((m) => ({ value: m, label: `${m} min` }))} />
          </Field>
          <Field label="Platforms">
            <div className="space-y-1.5">{["feed", "forum"].map((p) => (
              <Switch key={p} checked={o.platforms.includes(p)} onChange={() => setO({ ...o, platforms: o.platforms.includes(p) ? o.platforms.filter((x: string) => x !== p) : [...o.platforms, p] })}
                label={p === "feed" ? "Feed (X / TikTok style)" : "Forum (Reddit style)"} />))}</div>
          </Field>
        </div>
        <div className="mt-4"><Switch checked={o.listening} onChange={(v) => setO({ ...o, listening: v })} label="Seed the run with live social posts about this topic" /></div>
        <div className="mt-4 flex items-center gap-2">
          <Button variant={ready ? "secondary" : "primary"} onClick={prepare} loading={busy && !ready} disabled={preparing || sim.status === "running"}>
            {ready ? "Regenerate environment" : "Prepare environment"}</Button>
          {ready && <span className="text-xs text-muted">Depth changes take effect after regenerating.</span>}
        </div>
        {preparing && (
          <div className="mt-4">
            <div className="mb-1.5 flex justify-between text-[13px]"><span>{stream.envProgress?.message || "Starting…"}</span><span className="num text-muted">{fmt.pct(stream.envProgress?.progress ?? 0.05)}</span></div>
            <Progress value={stream.envProgress?.progress ?? 0.05} />
          </div>
        )}
        {sim.status === "graph_ready" && sim.error && <Callout tone="neg" className="mt-3">{sim.error}</Callout>}
      </Section>

      {ready && (
        <>
          <Section title="Generated configuration">
            <KV rows={[["Start (UTC)", fmt.date(cfg.time?.start)], ["Rounds", `${cfg.time?.rounds} × ${cfg.time?.minutes_per_round} min`],
              ["Audience", `${fmt.n(cfg.audience_size)} agents`], ["Agents", `${fmt.n(cfg.agents?.voice)} voice · ${cfg.agents?.stakeholders} stakeholder · ${fmt.n(cfg.agents?.crowd)} crowd`],
              ...(cfg.events?.hot_topics?.length ? [["Hot topics", cfg.events.hot_topics.join(", ")] as [string, string]] : [])]} />
            {cfg.events?.narrative && <p className="mt-3 text-[13px] leading-relaxed text-muted">{cfg.events.narrative}</p>}
            <div className="mt-4 space-y-4">
              {Object.entries(plat).map(([k, p]: any) => (
                <div key={k} className="rounded-md border border-line p-3">
                  <div className="mb-2 flex items-center justify-between"><span className="text-[13px] font-medium">{k === "feed" ? "Feed recommender" : "Forum recommender"}</span>
                    <Switch checked={p.enabled} onChange={(v) => setPlat({ ...plat, [k]: { ...p, enabled: v } })} /></div>
                  {["recency_weight", "popularity_weight", "relevance_weight", "echo_chamber"].map((w) => (
                    <div key={w} className="mb-1.5 grid grid-cols-[120px_1fr_40px] items-center gap-3 text-xs">
                      <span className="capitalize text-muted">{w.replace("_weight", "").replace("_", " ")}</span>
                      <Slider value={p[w]} min={0} max={1} step={0.05} onChange={(v) => setPlat({ ...plat, [k]: { ...p, [w]: v } })} />
                      <span className="num text-right">{p[w].toFixed(2)}</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </Section>

          <Section title="Scheduled events" right={<Button size="sm" onClick={() => setEvents([...events, { round: Math.ceil((cfg.time?.rounds || 2) / 2), text: "", source: "user" }])}><Plus className="h-3.5 w-3.5" />Add</Button>}>
            {events.length === 0 && <p className="text-[13px] text-muted">No scheduled events. Add one to test how a news story or competitor move would shift the conversation. You can also inject events live during the run.</p>}
            <div className="space-y-2">
              {events.map((e, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Input type="number" className="w-16" min={1} max={cfg.time?.rounds} value={e.round} onChange={(ev) => setEvents(events.map((x, j) => j === i ? { ...x, round: Number(ev.target.value) } : x))} />
                  <Input value={e.text} placeholder="What happens…" onChange={(ev) => setEvents(events.map((x, j) => j === i ? { ...x, text: ev.target.value } : x))} />
                  <Button size="icon-sm" variant="ghost" onClick={() => setEvents(events.filter((_, j) => j !== i))}><Trash2 className="h-3.5 w-3.5" /></Button>
                </div>
              ))}
            </div>
            <div className="mt-3"><Button size="sm" onClick={saveConfig}>Save configuration</Button></div>
          </Section>

          {cfg.external_seed?.length > 0 && (
            <Section title="Live posts seeding the conversation">
              <div className="divide-y divide-line overflow-hidden rounded-md border border-line">
                {cfg.external_seed.slice(0, 8).map((p: any, i: number) => (
                  <div key={i} className="px-3 py-2 text-[13px]">
                    <div className="mb-1 flex items-center gap-1.5 text-xs text-muted"><span className="font-medium capitalize text-fg">{p.platform}</span>· @{p.author}
                      {p.url && <a href={p.url} target="_blank" rel="noreferrer" className="ml-auto text-muted hover:text-fg"><ExternalLink className="h-3 w-3" /></a>}</div>
                    <div dir="auto" className="line-clamp-3 leading-relaxed">{p.text}</div>
                  </div>
                ))}
              </div>
            </Section>
          )}

          <Section title={`Agents (${fmt.n(list.length)})`}
            right={<Segmented value={filter} onChange={setFilter} options={[{ value: "all", label: "All" }, { value: "voice", label: "Voice" }, { value: "stakeholder", label: "Stakeholder" }]} />}>
            <div className="max-h-[420px] overflow-y-auto rounded-md border border-line">
              <table className="dt">
                <thead><tr><th>Agent</th><th>Profile</th><th>Stance</th><th className="!text-right">Activity</th></tr></thead>
                <tbody>{list.map((a) => (
                  <tr key={a.ref} className="hoverable" onClick={() => onAgent(a.ref)}>
                    <td className="whitespace-nowrap"><span className="mr-2 inline-block h-2 w-2 rounded-[2px]" style={{ background: REGION_COLORS[a.region] }} />
                      <span className="font-medium">{a.name}</span>{a.kind === "stakeholder" && <span className="ml-1.5 text-xs text-muted">account</span>}</td>
                    <td className="max-w-0 w-full"><div className="truncate text-xs text-muted">{a.kind === "stakeholder" ? `${a.persona.role} · ${a.persona.description || ""}`
                      : `${a.persona.age} · ${a.persona.origin} · ${a.persona.city} · ${a.persona.profession}`}</div></td>
                    <td className="whitespace-nowrap text-xs capitalize"><span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full" style={{ background: STANCE_COLORS[a.persona.stance] }} />{a.persona.stance}</td>
                    <td className="r text-xs text-muted">{Math.round((a.config.activity || 0) * 100)}%</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </Section>

          <div className="sticky bottom-0 border-t border-line bg-panel px-5 py-4">
            <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
              <span className="font-medium text-fg">Estimated model calls</span>
              {Object.entries(cfg.credits || {}).filter(([k]) => k !== "total").map(([k, v]: any) => <span key={k}><span className="capitalize">{k.replace("_", " ")}</span> <span className="num text-fg">{fmt.n(v)}</span></span>)}
            </div>
            <Button variant="primary" size="lg" className="w-full" onClick={start} loading={busy} disabled={!["ready", "completed", "failed", "cancelled"].includes(sim.status)}>
              <Play className="h-4 w-4" />{sim.status === "completed" ? "Run again" : "Start simulation"} · {fmt.n(cfg.credits?.total)} calls
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
