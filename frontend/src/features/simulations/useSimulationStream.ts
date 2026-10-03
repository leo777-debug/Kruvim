import { useEffect, useRef, useState } from "react";
import type { GraphHandle } from "@/components/graph/LiveGraph";
import { streamEvents } from "@/lib/api";
import { ACTION_COLORS } from "@/lib/colors";
import type { GEdge, GNode, SimEvent } from "@/lib/types";

export interface FeedItem {
  key: string;
  kind: "reaction" | "action" | "event" | "system";
  platform: "feed" | "forum" | "both";
  round: number;
  agent?: string;
  name?: string;
  handle?: string;
  region?: string;
  agentKind?: string;
  action?: string;
  content?: string;
  score?: number;
  opinion?: number;
  target?: number;
  time?: string;
  extra?: any;
}

export interface StreamState {
  nodes: GNode[];
  edges: GEdge[];
  graphVersion: number;
  graphProgress: { message: string; progress: number } | null;
  envProgress: { message: string; progress: number } | null;
  context: Record<string, any> | null;
  ontology: any;
  round: { round: number; rounds: number; sim_time?: string; clocks?: Record<string, string> } | null;
  timeline: any[];
  feed: FeedItem[];
  opinions: Record<string, number>;
  reactions: Record<string, any>;
  reactionsB: Record<string, any>;
  reactionProgress: [number, number] | null;
  status: string | null;
  lastError: string | null;
  report: { outline?: any; sections: Record<number, { title: string; content: string }>; log: any[]; status?: string };
  surveyAnswers: Record<string, any[]>;
  connected: "open" | "closed" | "error" | "connecting";
  lastSeq: number;
}

const initial = (): StreamState => ({
  nodes: [], edges: [], graphVersion: 0, graphProgress: null, envProgress: null, context: null, ontology: null, round: null, timeline: [],
  feed: [], opinions: {}, reactions: {}, reactionsB: {}, reactionProgress: null, status: null, lastError: null,
  report: { sections: {}, log: [] }, surveyAnswers: {}, connected: "connecting", lastSeq: 0,
});

export function useSimulationStream(simId: string | undefined, graphRef: React.RefObject<GraphHandle>, onTerminal?: (type: string) => void) {
  const store = useRef<StreamState>(initial());
  const nodeIdx = useRef<Map<string, GNode>>(new Map());
  const edgeKeys = useRef<Set<string>>(new Set());
  const [, setTick] = useState(0);
  const pending = useRef(false);
  const term = useRef(onTerminal);
  term.current = onTerminal;

  useEffect(() => {
    if (!simId) return;
    store.current = initial();
    nodeIdx.current = new Map();
    edgeKeys.current = new Set();
    setTick((x) => x + 1);

    const flush = () => {
      if (pending.current) return;
      pending.current = true;
      setTimeout(() => { pending.current = false; setTick((x) => x + 1); }, 120);
    };
    const s = () => store.current;
    const pushFeed = (it: FeedItem) => {
      s().feed.push(it);
      if (s().feed.length > 4000) s().feed.splice(0, 1000);
    };

    const apply = (ev: SimEvent) => {
      const p = ev.payload || {};
      const live = !ev.t || Date.now() / 1000 - ev.t < 10;
      s().lastSeq = ev.seq;
      switch (ev.type) {
        case "graph.delta": {
          for (const n of p.nodes || []) {
            if (nodeIdx.current.has(n.id)) continue;
            const anchor = guessAnchor(n, nodeIdx.current);
            const node: GNode = { ...n, x: anchor ? anchor.x! + (Math.random() - 0.5) * 30 : undefined, y: anchor ? anchor.y! + (Math.random() - 0.5) * 30 : undefined };
            if (!live) node.__born = 0;
            nodeIdx.current.set(n.id, node);
            s().nodes.push(node);
          }
          for (const e of p.edges || []) {
            const k = e.id != null ? String(e.id) : `${e.source}|${e.target}|${e.relation}`;
            if (edgeKeys.current.has(k) || !nodeIdx.current.has(e.source) || !nodeIdx.current.has(e.target)) continue;
            edgeKeys.current.add(k);
            s().edges.push({ ...e });
          }
          for (const update of p.updated_edges || []) {
            const old = s().edges.find((e) => e.id === update.id);
            if (old) Object.assign(old, { valid_until_round: update.valid_until_round, valid_until_at: update.valid_until_at });
          }
          s().graphVersion++;
          break;
        }
        case "graph.prune": {
          const drop = (n: GNode) => (p.prefix && n.id.startsWith(p.prefix)) || (p.min_round != null && (n.round ?? -1) >= p.min_round);
          const gone = new Set(s().nodes.filter(drop).map((n) => n.id));
          if (!gone.size && p.min_round == null) break;
          s().nodes = s().nodes.filter((n) => !gone.has(n.id));
          gone.forEach((id) => nodeIdx.current.delete(id));
          const id = (v: any) => (typeof v === "string" ? v : v.id);
          s().edges = s().edges.filter((e) => {
            const keep = !gone.has(id(e.source)) && !gone.has(id(e.target)) && !(p.min_round != null && (e.round ?? -1) >= p.min_round);
            if (!keep) edgeKeys.current.delete(e.id != null ? String(e.id) : `${id(e.source)}|${id(e.target)}|${e.relation}`);
            return keep;
          });
          s().graphVersion++;
          break;
        }
        case "graph.progress": s().graphProgress = p; s().status = "building_graph"; break;
        case "graph.context": s().context = p.regions; break;
        case "graph.completed": s().graphProgress = { message: "Graph complete", progress: 1 }; s().ontology = p.ontology; s().status = "graph_ready"; term.current?.(ev.type); break;
        case "graph.failed": s().lastError = p.message; s().status = "failed"; term.current?.(ev.type); break;
        case "env.progress": s().envProgress = p; s().status = "preparing"; break;
        case "env.completed": s().envProgress = { message: "Environment ready", progress: 1 }; s().status = "ready"; term.current?.(ev.type); break;
        case "env.failed": s().lastError = p.message; s().status = "graph_ready"; term.current?.(ev.type); break;
        case "simulation.queued": s().status = "queued"; s().feed = []; s().timeline = []; s().reactions = {}; s().opinions = {}; break;
        case "simulation.started": s().status = "running"; break;
        case "round.start": s().round = p; break;
        case "round.end": {
          s().timeline.push(p);
          s().round = { ...(s().round || { round: p.round, rounds: 0 }), round: p.round };
          if (live) graphRef.current?.ping("content:A");
          break;
        }
        case "reaction": {
          const key = `agent:${p.agent}`;
          if (p.variant === "B") { s().reactionsB[p.agent] = p.r; break; }
          s().reactions[p.agent] = p.r;
          s().opinions[key] = p.r.score;
          s().reactionProgress = p.progress;
          const n = nodeIdx.current.get(key);
          pushFeed({ key: `r${ev.seq}`, kind: "reaction", platform: "both", round: 0, agent: p.agent, name: n?.label, region: n?.attrs?.region,
            agentKind: n?.type, content: p.r.quote, score: p.r.score, extra: p.r });
          if (live) {
            graphRef.current?.fly(key, "content:A", p.r.score >= 6.5 ? "#59a14f" : p.r.score < 4 ? "#c43a2c" : "#9aa1ac");
          }
          for (const a of p.actions || []) {
            pushFeed({ key: `r${ev.seq}-${a.type}`, kind: "action", platform: a.platform, round: 0, agent: p.agent, name: n?.label, region: n?.attrs?.region,
              agentKind: n?.type, action: a.type, content: a.content, target: a.target, opinion: p.r.score });
          }
          break;
        }
        case "actions": {
          const key = `agent:${p.agent}`;
          s().opinions[key] = p.opinion;
          for (const a of p.actions || []) {
            pushFeed({ key: `a${ev.seq}-${a.type}-${a.post_id ?? a.target ?? ""}`, kind: "action", platform: p.platform, round: p.round, agent: p.agent,
              name: p.name, handle: p.handle, region: p.region, agentKind: p.kind, action: a.type, content: a.content, target: a.target ?? a.target_ref,
              opinion: p.opinion, time: p.time });
            if (live) {
              const tgt = a.target != null ? `post:${a.target}` : a.target_ref ? `agent:${a.target_ref}` : "content:A";
              graphRef.current?.fly(key, nodeIdx.current.has(tgt) ? tgt : "content:A", ACTION_COLORS[a.type] || "#e2e8f0");
            }
          }
          break;
        }
        case "event.injected":
          pushFeed({ key: `e${ev.seq}`, kind: "event", platform: "both", round: p.round, content: p.text, extra: { source: p.source } });
          if (live) graphRef.current?.ping("content:A", "#fb7185");
          break;
        case "simulation.paused": s().status = "paused"; break;
        case "simulation.resumed": s().status = "running"; break;
        case "simulation.completed": s().status = "completed"; term.current?.(ev.type); break;
        case "simulation.failed": s().status = "failed"; s().lastError = p.message; term.current?.(ev.type); break;
        case "report.started": s().report = { sections: {}, log: [], status: "running" }; break;
        case "report.outline": s().report.outline = p; break;
        case "report.log": s().report.log.push(p); break;
        case "report.section": s().report.sections[p.index] = { title: p.title, content: p.content }; break;
        case "report.completed": s().report.status = "done"; term.current?.(ev.type); break;
        case "report.failed": s().report.status = "failed"; s().lastError = p.message; term.current?.(ev.type); break;
        case "survey.answer": (s().surveyAnswers[p.survey_id] ||= []).push(p); break;
        case "survey.completed": term.current?.(ev.type); break;
      }
      flush();
    };

    const stop = streamEvents(simId, apply, { onStatus: (st) => { store.current.connected = st; flush(); } });
    return stop;
  }, [simId, graphRef]);

  return store.current;
}

function guessAnchor(n: GNode, idx: Map<string, GNode>): GNode | undefined {
  if (n.kind === "agent" && n.attrs?.region) return idx.get(`region:${n.attrs.region}`);
  if (n.kind === "crowd" && n.attrs?.region) return idx.get(`region:${n.attrs.region}`);
  if (n.kind === "post") return idx.get("content:A");
  if (n.kind === "entity") return idx.get("content:A");
  return undefined;
}
