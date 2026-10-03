import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/overlay";
import { Card, Empty, Input, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { REGION_COLORS, STANCE_COLORS } from "@/lib/colors";
import { useReference } from "@/lib/queries";
import type { Simulation } from "@/lib/types";
import { fmt, platformName } from "@/lib/utils";

const PAGE = 50;
const SENT = { positive: "text-pos", negative: "text-neg", neutral: "text-muted" } as Record<string, string>;

export function TranscriptPanel({ sim, onAgent }: { sim: Simulation; onAgent: (r: string) => void }) {
  const ref = useReference();
  const [f, setF] = useState({ region: "", stance: "", sentiment: "", platform: "", kind: "", q: "" });
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  useEffect(() => { const t = setTimeout(() => setF((x) => ({ ...x, q })), 300); return () => clearTimeout(t); }, [q]);
  useEffect(() => setPage(0), [f]);
  const params = new URLSearchParams(Object.entries({ ...f, offset: String(page * PAGE), limit: String(PAGE) }).filter(([, v]) => v));
  const data = useQuery({ queryKey: ["transcript", sim.id, params.toString()], queryFn: () => api(`/simulations/${sim.id}/transcript?${params}`) });
  const any = (label: string) => [{ value: "*", label }];
  const set = (k: keyof typeof f) => (v: string) => setF({ ...f, [k]: v === "*" ? "" : v });
  const regions = (sim.audience?.regions?.length ? sim.audience.regions : (ref.data?.regions || []).map((r) => r.code)) as string[];
  const total = data.data?.total ?? 0;
  return (
    <Card className="overflow-hidden">
      <div className="border-b border-line px-4 py-3">
        <div className="section-title">Debate transcript</div>
        <p className="mt-0.5 text-xs text-muted">Everything the agents wrote during the simulation: posts, comments and quotes, in order. Filter to see how a group talked about it.</p>
      </div>
      <div className="grid gap-2 border-b border-line p-3 sm:grid-cols-3 xl:grid-cols-6">
        <div className="relative sm:col-span-3 xl:col-span-2"><Search className="absolute left-2.5 top-2 h-4 w-4 text-faint" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search what people said" className="pl-8" /></div>
        <Select value={f.region || "*"} onChange={set("region")} options={[...any("All regions"), ...regions.map((c) => ({ value: c, label: ref.data?.regions.find((r) => r.code === c)?.name || c }))]} />
        <Select value={f.stance || "*"} onChange={set("stance")} options={[...any("Any disposition"), ...(ref.data?.stances || []).map((s) => ({ value: s, label: s[0].toUpperCase() + s.slice(1) }))]} />
        <Select value={f.sentiment || "*"} onChange={set("sentiment")} options={[...any("Any sentiment"), { value: "positive", label: "Positive" }, { value: "neutral", label: "Neutral" }, { value: "negative", label: "Negative" }]} />
        <Select value={f.platform || "*"} onChange={set("platform")} options={[...any("Feed and forum"), { value: "feed", label: "Feed only" }, { value: "forum", label: "Forum only" }]} />
      </div>
      <div className="flex items-center justify-between border-b border-line bg-raised px-4 py-2 text-xs text-muted">
        <span>{fmt.n(total)} message{total === 1 ? "" : "s"}</span>
        <Select className="h-7 w-44" value={f.kind || "*"} onChange={set("kind")} options={[...any("People and accounts"), { value: "voice", label: "People only" }, { value: "stakeholder", label: "Accounts only" }]} />
      </div>
      {data.isLoading ? <div className="space-y-2 p-4"><Skeleton /><Skeleton /><Skeleton /></div>
        : total === 0 ? <Empty title="No messages match">Try removing a filter.</Empty> : (
          <div className="divide-y divide-line">
            {data.data.items.map((m: any) => (
              <div key={m.id} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
                  {m.region && <span className="h-2 w-2 rounded-[2px]" style={{ background: REGION_COLORS[m.region] }} />}
                  <button onClick={() => m.author_ref?.includes(":") && onAgent(m.author_ref)} className="font-medium text-fg hover:underline">{m.author}</button>
                  <span className="text-muted">{[m.age && `${m.age}`, m.region, m.author_kind === "stakeholder" ? "account" : null].filter(Boolean).join(" · ")}</span>
                  {m.stance && <span className="inline-flex items-center gap-1 capitalize text-muted"><span className="h-1.5 w-1.5 rounded-full" style={{ background: STANCE_COLORS[m.stance] }} />{m.stance}</span>}
                  <span className={`capitalize ${SENT[m.sentiment]}`}>{m.sentiment}</span>
                  <span className="ml-auto text-faint">{platformName(m.platform)} · {m.kind} · round {m.round}</span>
                </div>
                {m.reply_to && <div className="mt-1 border-l-2 border-line-strong pl-2 text-xs text-muted">Replying to {m.reply_to.author}: “{m.reply_to.content}”</div>}
                <div dir="auto" className="mt-1 text-[14px] leading-relaxed">{m.content}</div>
              </div>
            ))}
          </div>
        )}
      {total > PAGE && (
        <div className="flex items-center justify-between border-t border-line px-4 py-2.5 text-xs text-muted">
          <span>{page * PAGE + 1}–{Math.min(total, (page + 1) * PAGE)} of {fmt.n(total)}</span>
          <div className="flex gap-2"><Button size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</Button>
            <Button size="sm" disabled={(page + 1) * PAGE >= total} onClick={() => setPage(page + 1)}>Next</Button></div>
        </div>
      )}
    </Card>
  );
}
