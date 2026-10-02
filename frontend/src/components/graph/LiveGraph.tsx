import { Crosshair, Eye, EyeOff, Pause, Play, Search, Tag } from "lucide-react";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import ForceGraph2D, { type ForceGraphMethods } from "react-force-graph-2d";
import { ENTITY_PALETTE, KIND_COLORS, REGION_COLORS, STANCE_COLORS, scoreColor } from "@/lib/colors";
import type { GEdge, GNode } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface GraphHandle {
  fly: (from: string, to: string, color?: string) => void;
  ping: (id: string, color?: string) => void;
  focus: (id: string) => void;
  fit: () => void;
}

type ColorMode = "kind" | "opinion" | "region" | "stance";
const KINDS = [
  { key: "entity", label: "Entities" }, { key: "signal", label: "Live signals" }, { key: "agent", label: "Agents" },
  { key: "post", label: "Posts" }, { key: "crowd", label: "Crowd" }, { key: "region", label: "Regions" },
];

interface Props {
  nodes: GNode[];
  edges: GEdge[];
  version: number;
  live?: boolean;
  opinions?: Record<string, number>;
  onSelect?: (n: GNode | null) => void;
  selectedId?: string | null;
  height?: number | string;
  className?: string;
  defaultHidden?: string[];
  title?: string;
}

const nid = (x: string | GNode) => (typeof x === "string" ? x : x.id);

export const LiveGraph = forwardRef<GraphHandle, Props>(function LiveGraph(
  { nodes, edges, version, live, opinions, onSelect, selectedId, height = 560, className, defaultHidden = [], title }, ref,
) {
  const fg = useRef<ForceGraphMethods<any, any>>();
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 560 });
  const [hidden, setHidden] = useState<Set<string>>(new Set(defaultHidden));
  const [labels, setLabels] = useState(false);
  const [mode, setMode] = useState<ColorMode>("kind");
  const [paused, setPaused] = useState(false);
  const [q, setQ] = useState("");
  const [hover, setHover] = useState<GNode | null>(null);
  const flights = useRef<{ a: string; b: string; t0: number; color: string }[]>([]);
  const pings = useRef<{ id: string; t0: number; color: string }[]>([]);
  const lastActive = useRef<Record<string, number>>({});
  const fitted = useRef(false);
  const theme = useGraphTheme();

  useEffect(() => {
    const el = box.current!;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // entity type → colour, stable per graph
  const typeColor = useMemo(() => {
    const m: Record<string, string> = {};
    let i = 0;
    for (const n of nodes) if (n.kind === "entity" && !(n.type in m)) m[n.type] = ENTITY_PALETTE[i++ % ENTITY_PALETTE.length];
    return m;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version]);

  const degree = useMemo(() => {
    const d: Record<string, number> = {};
    for (const e of edges) { d[nid(e.source)] = (d[nid(e.source)] || 0) + 1; d[nid(e.target)] = (d[nid(e.target)] || 0) + 1; }
    return d;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version]);

  const data = useMemo(() => {
    const vis = nodes.filter((n) => !hidden.has(n.kind === "content" || n.kind === "region" ? (n.kind === "region" ? "region" : "x") : n.kind));
    const ids = new Set(vis.map((n) => n.id));
    const links = edges.filter((e) => ids.has(nid(e.source)) && ids.has(nid(e.target)));
    return { nodes: vis, links };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version, hidden]);

  const match = useMemo(() => {
    const t = q.trim().toLowerCase();
    return t ? new Set(nodes.filter((n) => n.label.toLowerCase().includes(t)).map((n) => n.id)) : null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, version]);

  const neighbours = useMemo(() => {
    const id = selectedId || hover?.id;
    if (!id) return null;
    const s = new Set([id]);
    for (const e of data.links) { if (nid(e.source) === id) s.add(nid(e.target)); if (nid(e.target) === id) s.add(nid(e.source)); }
    return s;
  }, [selectedId, hover, data]);

  useEffect(() => {
    const f = fg.current;
    if (!f) return;
    f.d3Force("charge")?.strength((n: GNode) => (n.kind === "post" ? -18 : n.kind === "signal" ? -30 : -90));
    f.d3Force("link")?.distance((l: GEdge) => {
      const s = l.source as GNode, t = l.target as GNode;
      if (s.kind === "post" || t.kind === "post") return 26;
      if (s.kind === "signal" || t.kind === "signal") return 40;
      return 70;
    }).strength(0.35);
  }, []);

  useEffect(() => {
    const f = fg.current as any;
    if (!f) return;
    f.d3AlphaTarget?.(live && !paused ? 0.018 : 0);
    if (!paused) f.d3ReheatSimulation?.();
    if (!fitted.current && nodes.length > 3) {
      fitted.current = true;
      setTimeout(() => f.zoomToFit?.(600, 60), 900);
    }
  }, [version, live, paused, nodes.length]);

  useImperativeHandle(ref, () => ({
    fly: (a, b, color = "#4e79a7") => {
      flights.current.push({ a, b, t0: performance.now(), color });
      lastActive.current[a] = performance.now();
      if (flights.current.length > 400) flights.current.splice(0, 100);
    },
    ping: (id, color = "rgb(33,85,205)") => {
      pings.current.push({ id, t0: performance.now(), color });
      lastActive.current[id] = performance.now();
    },
    focus: (id) => {
      const n = nodes.find((x) => x.id === id);
      if (n && n.x != null && n.y != null) { fg.current?.centerAt(n.x, n.y, 700); fg.current?.zoom(3, 700); }
    },
    fit: () => fg.current?.zoomToFit(600, 60),
  }), [nodes]);

  const color = useCallback((n: GNode): string => {
    if (n.kind === "agent") {
      if (mode === "region") return REGION_COLORS[n.attrs?.region] || "#94a3b8";
      if (mode === "stance") return STANCE_COLORS[n.attrs?.stance] || "#94a3b8";
      const op = opinions?.[n.id];
      if (mode === "opinion" || op != null) return op != null ? scoreColor(op) : n.type === "stakeholder" ? KIND_COLORS.stakeholder : "#94a3b8";
      return n.type === "stakeholder" ? KIND_COLORS.stakeholder : KIND_COLORS.agent;
    }
    if (n.kind === "entity") return typeColor[n.type] || KIND_COLORS.entity;
    if (n.kind === "region" || n.kind === "crowd") return mode === "kind" ? (n.kind === "crowd" ? KIND_COLORS.crowd : KIND_COLORS.region) : REGION_COLORS[n.attrs?.region || n.id.split(":")[1]] || "#94a3b8";
    if (n.kind === "post") return n.type.startsWith("event") ? KIND_COLORS.event : n.type.startsWith("creator") ? KIND_COLORS.content : n.attrs?.stance != null ? scoreColor(n.attrs.stance, 0.85) : KIND_COLORS.post;
    return KIND_COLORS[n.kind] || "#94a3b8";
  }, [mode, opinions, typeColor]);

  const radius = useCallback((n: GNode) => {
    const d = degree[n.id] || 0;
    switch (n.kind) {
      case "content": return 11;
      case "region": return 7;
      case "crowd": return 6 + Math.min(8, Math.log10((n.attrs?.size || 10) + 1) * 2);
      case "entity": return 3.5 + Math.min(7, Math.sqrt(d) * 1.4);
      case "signal": return 2.2;
      case "agent": return n.type === "stakeholder" ? 7 : 3 + Math.min(6, Math.log10((n.attrs?.followers || 0) + 1) * 1.6);
      case "post": return 1.8 + Math.min(4, Math.sqrt(d) * 0.8);
      default: return 3;
    }
  }, [degree]);

  const draw = useCallback((n: GNode, ctx: CanvasRenderingContext2D, scale: number) => {
    const now = performance.now();
    const born = n.__born ?? (n.__born = now);
    const grow = Math.min(1, (now - born) / 450);
    const r = radius(n) * (0.4 + 0.6 * (1 - Math.pow(1 - grow, 3)));
    const dim = (match && !match.has(n.id)) || (neighbours && !neighbours.has(n.id));
    const c = color(n);
    ctx.globalAlpha = dim ? 0.15 : 1;
    if (n.kind === "content") {
      ctx.strokeStyle = c; ctx.lineWidth = 1.5 / scale;
      ctx.beginPath(); ctx.arc(n.x!, n.y!, r + 3.5, 0, Math.PI * 2); ctx.stroke();
    }
    const act = lastActive.current[n.id];
    if (act && now - act < 2500) {
      const t = (now - act) / 2500;
      ctx.strokeStyle = c; ctx.lineWidth = 1.2 / scale; ctx.globalAlpha = (dim ? 0.1 : 0.7) * (1 - t);
      ctx.beginPath(); ctx.arc(n.x!, n.y!, r + 2 + t * 10, 0, Math.PI * 2); ctx.stroke();
      ctx.globalAlpha = dim ? 0.15 : 1;
    }
    ctx.fillStyle = c;
    ctx.beginPath();
    ctx.arc(n.x!, n.y!, r, 0, Math.PI * 2);
    ctx.fill();
    if (n.kind !== "post" && n.kind !== "signal") { ctx.strokeStyle = theme.halo; ctx.lineWidth = 1 / scale; ctx.stroke(); }
    if (n.kind === "agent" && n.attrs?.stance === "contrarian") {
      ctx.setLineDash([2 / scale, 2 / scale]); ctx.strokeStyle = STANCE_COLORS.contrarian; ctx.lineWidth = 1 / scale;
      ctx.beginPath(); ctx.arc(n.x!, n.y!, r + 1.8, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
    }
    if (n.id === selectedId) {
      ctx.strokeStyle = theme.brand; ctx.lineWidth = 2 / scale;
      ctx.beginPath(); ctx.arc(n.x!, n.y!, r + 3, 0, Math.PI * 2); ctx.stroke();
    }
    const showLabel = n.kind === "content" || n.kind === "region" || n.kind === "crowd" || (n.kind === "agent" && n.type === "stakeholder")
      || (n.kind === "entity" && (scale > 1.1 || (degree[n.id] || 0) > 4)) || (n.kind === "agent" && scale > 2.6) || n.id === selectedId || (match?.has(n.id) ?? false);
    if (showLabel && !dim) {
      const fs = Math.max(10 / scale, 2.2);
      ctx.font = `${n.kind === "content" || n.kind === "region" ? 600 : 500} ${fs}px "Inter Variable", Inter, sans-serif`;
      ctx.textAlign = "center"; ctx.textBaseline = "top";
      const txt = n.label.length > 34 ? n.label.slice(0, 32) + "…" : n.label;
      const y = n.y! + r + 2.5 / scale;
      ctx.lineWidth = 3 / scale; ctx.strokeStyle = theme.halo; ctx.lineJoin = "round";
      ctx.strokeText(txt, n.x!, y);
      ctx.fillStyle = theme.label;
      ctx.fillText(txt, n.x!, y);
    }
    ctx.globalAlpha = 1;
  }, [color, radius, match, neighbours, selectedId, degree, theme]);

  const linkColor = useCallback((l: GEdge) => {
    const s = l.source as GNode, t = l.target as GNode;
    const dim = neighbours && !(neighbours.has(s.id) && neighbours.has(t.id));
    if (dim) return theme.edgeDim;
    const rel = l.relation;
    if (rel === "replied_to" || rel === "commented_on") return "rgba(78,121,167,0.45)";
    if (rel === "reposted" || rel === "quoted") return "rgba(89,161,79,0.45)";
    if (rel === "liked" || rel === "upvoted" || rel === "engaged") return "rgba(225,87,89,0.3)";
    if (rel === "follows") return "rgba(201,154,46,0.4)";
    return theme.edge;
  }, [neighbours, theme]);

  const postFrame = useCallback((ctx: CanvasRenderingContext2D, scale: number) => {
    const now = performance.now();
    const byId = new Map<string, GNode>();
    for (const n of data.nodes) byId.set(n.id, n);
    const keep: typeof flights.current = [];
    for (const f of flights.current) {
      const t = (now - f.t0) / 1100;
      if (t >= 1) { lastActive.current[f.b] = now; continue; }
      const a = byId.get(f.a), b = byId.get(f.b);
      if (!a || !b || a.x == null || b.x == null) { if (t < 0.2) keep.push(f); continue; }
      const e = 1 - Math.pow(1 - t, 2);
      const mx = (a.x + b.x!) / 2 - (b.y! - a.y!) * 0.18, my = (a.y! + b.y!) / 2 + (b.x! - a.x) * 0.18;
      const x = (1 - e) * (1 - e) * a.x + 2 * (1 - e) * e * mx + e * e * b.x!;
      const y = (1 - e) * (1 - e) * a.y! + 2 * (1 - e) * e * my + e * e * b.y!;
      ctx.strokeStyle = f.color; ctx.globalAlpha = 0.35 * (1 - t); ctx.lineWidth = 1 / scale;
      ctx.beginPath(); ctx.moveTo(a.x, a.y!); ctx.quadraticCurveTo(mx, my, b.x!, b.y!); ctx.stroke();
      ctx.globalAlpha = 1; ctx.fillStyle = f.color;
      ctx.beginPath(); ctx.arc(x, y, 2.4 / Math.sqrt(scale), 0, Math.PI * 2); ctx.fill();
      keep.push(f);
    }
    flights.current = keep;
    const pk: typeof pings.current = [];
    for (const p of pings.current) {
      const t = (now - p.t0) / 1400;
      if (t >= 1) continue;
      const n = byId.get(p.id);
      if (n && n.x != null) {
        ctx.strokeStyle = p.color; ctx.globalAlpha = 0.8 * (1 - t); ctx.lineWidth = 1.5 / scale;
        ctx.beginPath(); ctx.arc(n.x, n.y!, radius(n) + 3 + t * 22, 0, Math.PI * 2); ctx.stroke(); ctx.globalAlpha = 1;
      }
      pk.push(p);
    }
    pings.current = pk;
    if (labels && scale > 0.8) {
      ctx.font = `${Math.max(8 / scale, 1.6)}px "Inter Variable", Inter, sans-serif`;
      ctx.textAlign = "center";
      ctx.fillStyle = theme.muted;
      for (const l of data.links.slice(0, 1500)) {
        const s = l.source as GNode, t = l.target as GNode;
        if (s.kind === "post" || t.kind === "post" || s.x == null) continue;
        ctx.fillText(l.relation.replace(/_/g, " "), (s.x + t.x!) / 2, (s.y! + t.y!) / 2);
      }
    }
  }, [data, labels, radius, theme]);

  const legend = useMemo(() => {
    const items: { c: string; l: string }[] = [];
    Object.entries(typeColor).slice(0, 8).forEach(([t, c]) => items.push({ c, l: t }));
    items.push({ c: KIND_COLORS.content, l: "Content" }, { c: KIND_COLORS.signal, l: "Live signal" }, { c: KIND_COLORS.region, l: "Region" });
    if (nodes.some((n) => n.kind === "agent")) items.push({ c: KIND_COLORS.agent, l: "Agent" }, { c: KIND_COLORS.stakeholder, l: "Stakeholder" });
    if (nodes.some((n) => n.kind === "crowd")) items.push({ c: KIND_COLORS.crowd, l: "Crowd cluster" });
    return items;
  }, [typeColor, nodes]);

  const toolbar = (
    <div className="flex min-h-[44px] flex-wrap items-center gap-2 border-b border-line bg-panel px-3 py-1.5">
      {title && <div className="mr-1 truncate text-[13px] font-semibold">{title}</div>}
      <div className="flex h-7 items-center gap-1.5 rounded-md border border-line-strong bg-panel px-2">
        <Search className="h-3.5 w-3.5 text-faint" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find node" aria-label="Find node" className="w-28 bg-transparent text-xs outline-none placeholder:text-faint" />
      </div>
      <div className="ml-auto flex items-center gap-2">
        <span className="hidden text-xs text-muted 2xl:inline">Colour by</span>
        <div className="flex h-7 items-center rounded-md border border-line-strong bg-panel p-0.5" role="group" aria-label="Colour nodes by">
          {(["kind", "opinion", "region", "stance"] as ColorMode[]).map((m) => (
            <button key={m} onClick={() => setMode(m)} className={cn("rounded-[4px] px-2 py-0.5 text-xs capitalize", mode === m ? "bg-raised font-medium text-fg" : "text-muted hover:text-fg")}>{m}</button>
          ))}
        </div>
        <div className="flex h-7 items-center rounded-md border border-line-strong bg-panel p-0.5">
          <IconBtn onClick={() => setLabels(!labels)} active={labels} title="Show relation labels"><Tag className="h-3.5 w-3.5" /></IconBtn>
          <IconBtn onClick={() => setPaused(!paused)} title={paused ? "Resume layout" : "Freeze layout"}>{paused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}</IconBtn>
          <IconBtn onClick={() => fg.current?.zoomToFit(600, 60)} title="Fit to view"><Crosshair className="h-3.5 w-3.5" /></IconBtn>
        </div>
      </div>
    </div>
  );

  const footer = (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5 border-t border-line bg-panel px-3 py-2">
      <div className="flex min-w-0 flex-wrap gap-x-3 gap-y-1">
        {legend.map((x) => (
          <span key={x.l} className="flex items-center gap-1.5 text-xs capitalize text-muted"><span className="h-2 w-2 rounded-full" style={{ background: x.c }} />{x.l}</span>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-1">
        {KINDS.filter((k) => nodes.some((n) => n.kind === k.key)).map((k) => (
          <button key={k.key} onClick={() => setHidden((h) => { const s = new Set(h); s.has(k.key) ? s.delete(k.key) : s.add(k.key); return s; })}
            title={hidden.has(k.key) ? `Show ${k.label.toLowerCase()}` : `Hide ${k.label.toLowerCase()}`}
            className={cn("flex items-center gap-1 rounded px-1.5 py-0.5 text-xs hover:bg-raised", hidden.has(k.key) ? "text-faint line-through" : "text-muted hover:text-fg")}>
            {hidden.has(k.key) ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}{k.label}
          </button>
        ))}
        <span className="num ml-1 border-l border-line pl-2 text-xs text-muted">{fmtInt(data.nodes.length)} nodes · {fmtInt(data.links.length)} edges</span>
      </div>
    </div>
  );

  return (
    <div className={cn("flex flex-col overflow-hidden rounded-md border border-line bg-panel", className)} style={{ height }}>
      {toolbar}
      <div ref={box} className="relative min-h-0 flex-1 bg-[var(--graph-bg)]">
        <div className="dot-grid absolute inset-0" />
        <ForceGraph2D
          ref={fg as any}
          width={size.w}
          height={size.h}
          graphData={data as any}
          backgroundColor="rgba(0,0,0,0)"
          nodeId="id"
          nodeRelSize={4}
          nodeCanvasObject={draw as any}
          nodePointerAreaPaint={(n: any, c: string, ctx: CanvasRenderingContext2D) => { ctx.fillStyle = c; ctx.beginPath(); ctx.arc(n.x, n.y, radius(n) + 3, 0, Math.PI * 2); ctx.fill(); }}
          linkColor={linkColor as any}
          linkWidth={(l: any) => Math.min(3, 0.5 + Math.log10((l.weight || 1) + 1))}
          linkCurvature={(l: any) => (l.relation === "replied_to" || l.relation === "follows" ? 0.25 : 0)}
          linkDirectionalParticles={(l: any) => (live && (l.relation === "commented_on" || l.relation === "reposted" || l.relation === "replied_to" || l.relation === "engaged") ? 1 : 0)}
          linkDirectionalParticleSpeed={0.006}
          linkDirectionalParticleWidth={1.6}
          onRenderFramePost={postFrame as any}
          autoPauseRedraw={false}
          cooldownTicks={live ? Infinity : 400}
          d3VelocityDecay={0.32}
          onNodeHover={(n: any) => setHover(n)}
          onNodeClick={(n: any) => onSelect?.(n)}
          onBackgroundClick={() => onSelect?.(null)}
          nodeLabel={(n: any) => `<div style="max-width:280px;padding:8px 10px;border-radius:6px;background:#111827;color:#f3f4f6;font:12px 'Inter Variable',Inter,sans-serif;box-shadow:0 8px 24px rgba(16,24,40,.25)">
            <div style="font-weight:600;margin-bottom:2px">${esc(n.label)}</div><div style="color:#9ca3af;font-size:11px;text-transform:capitalize">${esc(n.kind)} · ${esc(n.type)}</div>
            ${n.summary ? `<div style="margin-top:4px;color:#d1d5db;line-height:1.45">${esc(n.summary.slice(0, 220))}</div>` : ""}</div>`}
        />
      </div>
      {footer}
    </div>
  );
});
function fmtInt(n: number) {
  return n.toLocaleString("en-US");
}

/** Canvas colours from the CSS theme tokens; re-read when the light/dark class flips. */
function useGraphTheme() {
  const read = () => {
    const s = getComputedStyle(document.documentElement);
    const rgb = (v: string) => `rgb(${s.getPropertyValue(v).trim().split(/\s+/).join(",")})`;
    return {
      label: s.getPropertyValue("--graph-label").trim() || "#1f2937",
      edge: s.getPropertyValue("--graph-edge").trim() || "rgba(75,85,99,.22)",
      edgeDim: "rgba(148,163,184,0.06)",
      halo: s.getPropertyValue("--graph-bg").trim() || "#fbfbfc",
      brand: rgb("--brand"),
      muted: rgb("--muted"),
    };
  };
  const [t, setT] = useState(read);
  useEffect(() => {
    const mo = new MutationObserver(() => setT(read()));
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => mo.disconnect();
  }, []);
  return t;
}
function IconBtn({ children, onClick, active, title }: { children: React.ReactNode; onClick: () => void; active?: boolean; title: string }) {
  return <button title={title} aria-label={title} onClick={onClick} className={cn("rounded-[4px] p-1", active ? "bg-raised text-fg" : "text-muted hover:text-fg")}>{children}</button>;
}

function esc(s: string) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c] as string));
}
