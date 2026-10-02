import { ArrowRight, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Callout, KV, Progress } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { ENTITY_PALETTE } from "@/lib/colors";
import type { Simulation } from "@/lib/types";
import { fmt } from "@/lib/utils";
import type { StreamState } from "../useSimulationStream";

export function Section({ title, children, right }: { title: React.ReactNode; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <section className="border-b border-line px-5 py-5">
      <div className="mb-3 flex items-center justify-between gap-2"><h3 className="section-title">{title}</h3>{right}</div>
      {children}
    </section>
  );
}

export function GraphStep({ sim, stream, onNext, refetch }: { sim: Simulation; stream: StreamState; onNext: () => void; refetch: () => void }) {
  const [busy, setBusy] = useState(false);
  const building = sim.status === "building_graph";
  const ready = !["draft", "building_graph"].includes(sim.status) && !!sim.ontology?.entity_types;
  const card = sim.card || {};
  const ctx = stream.context || sim.config?.context || {};
  const entities = stream.nodes.filter((n) => n.kind === "entity");
  const byType = useMemo(() => {
    const m: Record<string, number> = {};
    for (const n of entities) m[n.type] = (m[n.type] || 0) + 1;
    return m;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream.graphVersion]);

  async function build() {
    setBusy(true);
    try {
      await api(`/simulations/${sim.id}/graph`, { method: "POST" });
      refetch();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not start");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="bg-panel">
      <Section title="Research question">
        <p className="text-[13px] leading-relaxed">{sim.requirement || <span className="text-muted">No question set. Edit the inputs to add one; the analyst answers it in the report.</span>}</p>
        <KV className="mt-3" rows={[["Format", <span className="capitalize">{sim.content?.type}</span>], ["Platform", sim.content?.platform],
          ["Regions", (sim.audience?.regions || []).join(", ") || "All"], ["Publish time", sim.publish_at ? fmt.date(sim.publish_at) : "Now"]]} />
      </Section>

      <Section title="Knowledge graph" right={ready && !building ? <Button size="sm" onClick={build} loading={busy}><RefreshCw className="h-3.5 w-3.5" />Rebuild</Button> : null}>
        {!ready && !building && (
          <div>
            <p className="text-[13px] leading-relaxed text-muted">Kruvim reads the content and background files, designs an ontology for this question, extracts entities and relations,
              and links them to current events in the audience's regions.</p>
            <Button variant="primary" className="mt-4" onClick={build} loading={busy}>Build knowledge graph</Button>
            {sim.status === "failed" && sim.error && <Callout tone="neg" className="mt-4">{sim.error}</Callout>}
          </div>
        )}
        {building && (
          <div>
            <div className="mb-2 flex items-center justify-between text-[13px]"><span>{stream.graphProgress?.message || "Starting…"}</span>
              <span className="num text-muted">{fmt.pct(stream.graphProgress?.progress ?? 0.02)}</span></div>
            <Progress value={stream.graphProgress?.progress ?? 0.02} />
          </div>
        )}
        {ready && (
          <KV rows={[["Entities", fmt.n(entities.length)], ["Relations", fmt.n(stream.edges.length)],
            ["Live signals linked", fmt.n(stream.nodes.filter((n) => n.kind === "signal").length)], ["Ontology", sim.ontology?.by || "–"]]} />
        )}
      </Section>

      {(card.summary || card.segments) && (
        <Section title="Content analysis">
          <div className="text-[13px] font-medium">{card.title}</div>
          <p className="mt-1 text-[13px] leading-relaxed text-muted">{card.summary}</p>
          <KV className="mt-3" rows={[
            ["Language", card.language || "–"], ["Tone", card.tone || "–"],
            ["Topics", Object.values(card.topic_labels || {}).join(", ") || "–"],
            ["Opening hook strength", card.hook ? fmt.pct(card.hook.strength) : "–"],
          ]} />
          {(card.segments || []).length > 0 && (
            <div className="mt-4 overflow-hidden rounded-md border border-line">
              <table className="dt">
                <thead><tr><th className="w-14">{card.timed ? "Time" : "Seg."}</th><th>Segment</th></tr></thead>
                <tbody>{(card.segments || []).slice(0, 12).map((s: any) => (
                  <tr key={s.i}><td className="num text-muted">{card.timed ? fmt.t(s.start) : s.i + 1}</td>
                    <td><div className="font-medium">{s.label}</div><div className="line-clamp-2 text-xs text-muted">{s.note || s.text}</div></td></tr>
                ))}</tbody>
              </table>
            </div>
          )}
          {card.sensitivity_flags?.length > 0 && <Callout tone="warn" title="Sensitivity flags" className="mt-3">{card.sensitivity_flags.join(" · ")}</Callout>}
        </Section>
      )}

      {sim.ontology?.entity_types && (
        <Section title="Ontology">
          <div className="overflow-hidden rounded-md border border-line">
            <table className="dt">
              <thead><tr><th>Entity type</th><th>Description</th><th className="!text-right">Found</th></tr></thead>
              <tbody>{sim.ontology.entity_types.map((e: any, i: number) => (
                <tr key={e.name}>
                  <td className="whitespace-nowrap"><span className="mr-2 inline-block h-2 w-2 rounded-full" style={{ background: ENTITY_PALETTE[i % ENTITY_PALETTE.length] }} />{e.name}</td>
                  <td className="text-xs text-muted">{e.description}</td>
                  <td className="r">{byType[e.name] ?? 0}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          {sim.ontology.relation_types?.length > 0 && <p className="mt-3 text-xs leading-relaxed text-muted"><span className="font-medium text-fg">Relations: </span>{sim.ontology.relation_types.map((r: any) => r.name.replace(/_/g, " ")).join(", ")}</p>}
          {sim.ontology.analysis_focus && <p className="mt-2 text-xs leading-relaxed text-muted"><span className="font-medium text-fg">Focus: </span>{sim.ontology.analysis_focus}</p>}
        </Section>
      )}

      {Object.keys(ctx).length > 0 && (
        <Section title="Live context at publish time">
          <div className="divide-y divide-line overflow-hidden rounded-md border border-line">
            {Object.entries(ctx).map(([code, c]: any) => (
              <div key={code} className="px-3 py-2.5">
                <div className="flex items-center justify-between gap-3 text-[13px]">
                  <span className="font-medium">{c.city}, {c.name}</span>
                  <span className="num whitespace-nowrap text-xs text-muted">{c.scheduled_local_time || c.local_time}{c.weather && ` · ${Math.round(c.weather.temp_c)}°C`}</span>
                </div>
                <p className="mt-1 text-xs leading-relaxed text-muted" dir="auto">{c.brief}</p>
                <div className="mt-1 text-[11px] text-faint">{c.archived ? "Archived snapshot" : c.brief_by === "template" ? "Automatic summary" : `Summary by ${c.brief_by}`}</div>
              </div>
            ))}
          </div>
        </Section>
      )}

      <div className="px-5 py-4">
        <Button variant="primary" className="w-full" disabled={!ready || building} onClick={onNext}>Continue to environment<ArrowRight className="h-4 w-4" /></Button>
      </div>
    </div>
  );
}
