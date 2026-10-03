import { useEffect, useRef } from "react";
import { Area, AreaChart, Bar as RBar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from "recharts";
import { REGION_COLORS, STANCE_COLORS, engColor, scoreColor } from "@/lib/colors";
import { cn, fmt } from "@/lib/utils";

const axis = { stroke: "rgb(var(--muted))", fontSize: 11, tickLine: false, axisLine: false } as const;
// Series colours (Tableau 10 subset): consistent across every chart.
export const SERIES = { a: "#2155cd", b: "#f28e2b", c: "#59a14f", d: "#b07aa1", neg: "#c43a2c" };
const grid = <CartesianGrid stroke="rgb(var(--line))" strokeDasharray="0" vertical={false} />;

function Tip({ active, payload, label, fmtv }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-line bg-panel px-2.5 py-1.5 text-xs shadow-pop">
      {label != null && <div className="mb-1 text-muted">{label}</div>}
      {payload.map((p: any) => (
        <div key={p.dataKey} className="flex items-center gap-2"><span className="h-2 w-2 rounded-[2px]" style={{ background: p.color }} />
          <span className="text-muted">{p.name}</span><span className="num ml-auto text-fg">{fmtv ? fmtv(p.value) : fmt.s2(p.value)}</span></div>
      ))}
    </div>
  );
}

export function OpinionTimeline({ data, height = 180 }: { data: any[]; height?: number }) {
  const rows = data.map((d) => ({ round: d.round, voice: d.voice_opinion, crowd: d.crowd_opinion, pol: d.polarization }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={rows} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
        {grid}
        <XAxis dataKey="round" {...axis} tickFormatter={(v) => `R${v}`} />
        <YAxis domain={[0, 10]} {...axis} />
        <Tooltip content={<Tip />} />
        <Legend iconType="square" iconSize={8} wrapperStyle={{ fontSize: 11, color: "rgb(var(--muted))" }} />
        <Line dataKey="voice" name="Voice agents" stroke={SERIES.a} strokeWidth={1.75} dot={false} isAnimationActive={false} />
        <Line dataKey="crowd" name="Crowd" stroke={SERIES.b} strokeWidth={1.75} dot={false} isAnimationActive={false} />
        <Line dataKey="pol" name="Polarisation (sd)" stroke={SERIES.neg} strokeWidth={1.25} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function ActivityChart({ data, height = 150 }: { data: any[]; height?: number }) {
  let prevF = 0, prevR = 0;
  const rows = data.map((d) => {
    const a = d.actions || {};
    const f = Object.entries(a).filter(([k]) => k.startsWith("feed:")).reduce((s, [, v]) => s + (v as number), 0);
    const r = Object.entries(a).filter(([k]) => k.startsWith("forum:")).reduce((s, [, v]) => s + (v as number), 0);
    const row = { round: d.round, feed: f - prevF, forum: r - prevR };
    prevF = f; prevR = r;
    return row;
  });
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
        {grid}
        <XAxis dataKey="round" {...axis} tickFormatter={(v) => `R${v}`} />
        <YAxis {...axis} />
        <Tooltip content={<Tip fmtv={(v: number) => fmt.n(v)} />} cursor={{ fill: "rgb(var(--raised))" }} />
        <RBar dataKey="feed" name="Feed actions" stackId="a" fill={SERIES.a} isAnimationActive={false} />
        <RBar dataKey="forum" name="Forum actions" stackId="a" fill={SERIES.b} radius={[1, 1, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ReachChart({ data, height = 150 }: { data: any[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data.map((d) => ({ round: d.round, views: d.creator_views }))} margin={{ top: 6, right: 8, left: -10, bottom: 0 }}>
                {grid}
        <XAxis dataKey="round" {...axis} tickFormatter={(v) => `R${v}`} />
        <YAxis {...axis} tickFormatter={(v) => fmt.k(v)} />
        <Tooltip content={<Tip fmtv={(v: number) => fmt.n(v)} />} />
        <Area dataKey="views" name="Views of the creator's post" stroke={SERIES.a} fill={SERIES.a} fillOpacity={0.08} strokeWidth={1.75} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function Histogram({ counts, mean, height = 110 }: { counts: number[]; mean?: number; height?: number }) {
  const rows = counts.map((c, i) => ({ bin: `${i}–${i + 1}`, c, i }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} margin={{ top: 4, right: 0, left: 0, bottom: 0 }} barCategoryGap={2}>
        <XAxis dataKey="bin" {...axis} interval={1} />
        <Tooltip content={<Tip fmtv={(v: number) => fmt.n(v)} />} cursor={{ fill: "rgb(var(--raised))" }} />
        <RBar dataKey="c" name="Agents" radius={[1, 1, 0, 0]} isAnimationActive={false}>
          {rows.map((r) => <Cell key={r.i} fill={scoreColor(r.i + 0.5, mean != null && Math.floor(mean) === r.i ? 1 : 0.75)} />)}
        </RBar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function LineSimple({ points, height = 150, yMax, color = SERIES.a, xFmt, yFmt, area }: {
  points: { x: number | string; y: number }[]; height?: number; yMax?: number; color?: string; xFmt?: (v: any) => string; yFmt?: (v: number) => string; area?: boolean;
}) {
  const C = area ? AreaChart : LineChart;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <C data={points} margin={{ top: 6, right: 8, left: -12, bottom: 0 }}>
        {grid}
        <XAxis dataKey="x" {...axis} tickFormatter={xFmt} />
        <YAxis {...axis} domain={[0, yMax ?? "auto"]} tickFormatter={yFmt} />
        <Tooltip content={<Tip fmtv={yFmt} />} />
        {area ? <Area dataKey="y" name="" stroke={color} fill={color} fillOpacity={0.08} strokeWidth={1.75} isAnimationActive={false} />
          : <Line dataKey="y" name="" stroke={color} strokeWidth={1.75} dot={{ r: 2.5, strokeWidth: 0, fill: color }} isAnimationActive={false} />}
      </C>
    </ResponsiveContainer>
  );
}

export function HeatGrid({ rows, columns }: { rows: { label: string; values: number[]; n?: number }[]; columns: string[] }) {
  return (
    <div className="overflow-x-auto">
      <div className="grid gap-[2px]" style={{ gridTemplateColumns: `170px repeat(${columns.length}, minmax(34px, 1fr))` }}>
        <div />
        {columns.map((c, i) => <div key={i} className="truncate text-center text-2xs text-muted" title={c}>{i + 1}</div>)}
        {rows.map((r) => [
          <div key={r.label} className="truncate pr-2 text-2xs text-muted" title={r.n ? `${fmt.n(r.n)} agents` : ""}>{r.label}</div>,
          ...r.values.map((v, i) => (
            <div key={r.label + i} className="num flex h-6 items-center justify-center text-[10.5px] text-white" style={{ background: engColor(v) }}
              title={`${r.label} · segment ${i + 1}: ${fmt.pct(v, 1)} still watching`}>{Math.round(v * 100)}</div>
          )),
        ])}
      </div>
    </div>
  );
}

export function BarList({ rows, max = 10, colorFor, valueFmt = fmt.s2 }: {
  rows: { label: string; value: number; sub?: string }[]; max?: number; colorFor?: (v: number) => string; valueFmt?: (v: number) => string;
}) {
  return (
    <div className="space-y-1.5">
      {rows.map((r) => (
        <div key={r.label} className="grid grid-cols-[minmax(0,140px)_1fr_48px] items-center gap-2.5 text-xs">
          <div className="truncate text-fg/85">{r.label} {r.sub && <span className="text-2xs text-faint">{r.sub}</span>}</div>
          <div className="h-2 overflow-hidden rounded-sm bg-line/70"><div className="h-full rounded-sm" style={{ width: `${Math.max(0, Math.min(1, r.value / max)) * 100}%`, background: colorFor ? colorFor(r.value) : SERIES.a }} /></div>
          <div className="num text-right text-fg/85">{valueFmt(r.value)}</div>
        </div>
      ))}
    </div>
  );
}

export function Dumbbell({ rows }: { rows: { label: string; a: number; b: number }[] }) {
  return (
    <div className="space-y-2">
      {rows.map((r) => {
        const lo = Math.min(r.a, r.b), hi = Math.max(r.a, r.b), d = r.b - r.a;
        return (
          <div key={r.label} className="grid grid-cols-[110px_1fr_44px] items-center gap-2 text-xs">
            <div className="truncate text-muted">{r.label}</div>
            <div className="relative h-4">
              <div className="absolute inset-y-1/2 left-0 right-0 h-px bg-line" />
              <div className="absolute top-1/2 h-0.5 -translate-y-1/2 rounded" style={{ left: `${lo * 10}%`, width: `${(hi - lo) * 10}%`, background: d >= 0 ? SERIES.c : SERIES.neg }} />
              <div className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-fg/70 bg-panel" style={{ left: `${r.a * 10}%` }} title={`A ${r.a}`} />
              <div className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-fg" style={{ left: `${r.b * 10}%` }} title={`B ${r.b}`} />
            </div>
            <div className={cn("num text-right", d >= 0 ? "text-pos" : "text-neg")}>{d >= 0 ? "+" : ""}{d.toFixed(2)}</div>
          </div>
        );
      })}
    </div>
  );
}

export function PopulationScatter({ sample, colorBy, onPick, height = 320 }: { sample: any; colorBy: "score" | "region" | "stance"; onPick?: (id: number) => void; height?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const tip = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const cv = ref.current!;
    const F: Record<string, number> = Object.fromEntries(sample.fields.map((f: string, i: number) => [f, i]));
    const rows: number[][] = sample.rows;
    const jit = rows.map((_, i) => ((Math.sin(i * 12.9898) * 43758.5453) % 1) - 0.5);
    let pts: [number, number, number][] = [];
    const pad = { l: 34, r: 10, t: 10, b: 22 };
    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const W = cv.clientWidth, H = height;
      cv.width = W * dpr; cv.height = H * dpr;
      const c = cv.getContext("2d")!;
      c.setTransform(dpr, 0, 0, dpr, 0, 0);
      c.clearRect(0, 0, W, H);
      const X = (v: number) => pad.l + ((v - 16) / 54) * (W - pad.l - pad.r);
      const Y = (v: number) => pad.t + (1 - v / 10) * (H - pad.t - pad.b);
      c.strokeStyle = "rgba(148,163,184,0.25)"; c.fillStyle = "rgba(107,114,128,0.95)"; c.font = "11px 'Inter Variable', Inter, sans-serif";
      for (const v of [0, 2.5, 5, 7.5, 10]) { c.beginPath(); c.moveTo(pad.l, Y(v)); c.lineTo(W - pad.r, Y(v)); c.stroke(); c.textAlign = "right"; c.fillText(String(v), pad.l - 6, Y(v) + 3); }
      c.textAlign = "center";
      for (const v of [16, 25, 35, 45, 55, 70]) c.fillText(String(v), X(v), H - 6);
      pts = [];
      rows.forEach((row, i) => {
        const x = X(row[F.age] + jit[i]), y = Y(row[F.score]);
        const col = colorBy === "region" ? REGION_COLORS[sample.regions[row[F.region]]] : colorBy === "stance" ? STANCE_COLORS[sample.stances[row[F.stance]]] : scoreColor(row[F.score]);
        c.globalAlpha = 0.6; c.fillStyle = col || "#94a3b8";
        c.beginPath(); c.arc(x, y, 1.4 + Math.min(4, Math.log10(row[F.followers] + 1)), 0, Math.PI * 2); c.fill();
        pts.push([x, y, i]);
      });
      c.globalAlpha = 1;
    };
    draw();
    const near = (mx: number, my: number) => { let b = -1, bd = 64; for (const [x, y, i] of pts) { const d = (x - mx) ** 2 + (y - my) ** 2; if (d < bd) { bd = d; b = i; } } return b; };
    const move = (e: MouseEvent) => {
      const r = cv.getBoundingClientRect();
      const i = near(e.clientX - r.left, e.clientY - r.top);
      const t = tip.current!;
      if (i < 0) { t.style.display = "none"; cv.style.cursor = "default"; return; }
      const row = rows[i];
      cv.style.cursor = "pointer";
      t.innerHTML = `<b>#${row[F.id]}</b> · ${row[F.age]} · ${sample.regions[row[F.region]]} · ${sample.stances[row[F.stance]]}<br/>projected <b>${row[F.score].toFixed(1)}</b>/10 · share ${(row[F.share] * 100).toFixed(0)}%`;
      t.style.display = "block"; t.style.left = `${Math.min(r.width - 220, e.clientX - r.left + 12)}px`; t.style.top = `${e.clientY - r.top + 12}px`;
    };
    const click = (e: MouseEvent) => { const r = cv.getBoundingClientRect(); const i = near(e.clientX - r.left, e.clientY - r.top); if (i >= 0) onPick?.(rows[i][F.id]); };
    cv.addEventListener("mousemove", move); cv.addEventListener("click", click);
    const ro = new ResizeObserver(draw); ro.observe(cv);
    return () => { cv.removeEventListener("mousemove", move); cv.removeEventListener("click", click); ro.disconnect(); };
  }, [sample, colorBy, height, onPick]);
  return (
    <div className="relative">
      <canvas ref={ref} style={{ width: "100%", height }} />
      <div ref={tip} className="pointer-events-none absolute z-10 hidden rounded-md border border-line bg-panel px-2.5 py-1.5 text-xs shadow-pop" />
    </div>
  );
}
