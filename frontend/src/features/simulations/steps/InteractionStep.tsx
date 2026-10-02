import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Search, Send } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/overlay";
import { Badge, Callout, Empty, Field, Input, Segmented, Status, Textarea, UnderlineTabs } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { REGION_COLORS, scoreColor, STANCE_COLORS } from "@/lib/colors";
import type { Simulation } from "@/lib/types";
import { cn, fmt, initials } from "@/lib/utils";
import type { StreamState } from "../useSimulationStream";

export function InteractionStep({ sim, stream }: { sim: Simulation; stream: StreamState }) {
  const [tab, setTab] = useState("agents");
  return (
    <div className="mx-auto max-w-[1400px] px-4 py-5 sm:px-6">
      <UnderlineTabs value={tab} onChange={setTab} className="mb-5" tabs={[
        { key: "agents", label: "Interview agents" },
        { key: "report", label: "Ask the analyst" },
        { key: "survey", label: "Surveys" },
      ]} />
      {tab === "agents" && <Agents sim={sim} />}
      {tab === "report" && <ReportChat sim={sim} />}
      {tab === "survey" && <Surveys sim={sim} stream={stream} />}
    </div>
  );
}

function Agents({ sim }: { sim: Simulation }) {
  const agents = useQuery({ queryKey: ["agents", sim.id, "all"], queryFn: () => api<any[]>(`/simulations/${sim.id}/agents`) });
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("all");
  const [sel, setSel] = useState<string | null>(null);
  const [popId, setPopId] = useState("");
  const list = useMemo(() => (agents.data || []).filter((a) => (kind === "all" || a.kind === kind) &&
    (!q || `${a.name} ${a.handle} ${a.persona.city} ${a.persona.stance} ${a.persona.profession}`.toLowerCase().includes(q.toLowerCase()))), [agents.data, q, kind]);
  useEffect(() => { if (!sel && agents.data?.length) setSel(agents.data[0].ref); }, [agents.data, sel]);
  return (
    <div className="grid h-[calc(100vh-260px)] min-h-[520px] gap-4 lg:grid-cols-[340px_1fr]">
      <div className="card flex min-h-0 flex-col">
        <div className="space-y-2 border-b border-line p-3">
          <div className="relative"><Search className="absolute left-2.5 top-2 h-4 w-4 text-faint" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, city, stance" className="pl-8" /></div>
          <Segmented value={kind} onChange={setKind} options={[{ value: "all", label: "All" }, { value: "voice", label: "Voice" }, { value: "stakeholder", label: "Stakeholder" }]} />
          <div className="flex items-center gap-1.5">
            <Input value={popId} onChange={(e) => setPopId(e.target.value.replace(/\D/g, ""))} placeholder="Population agent ID (0–999,999)" className="h-7 text-xs" />
            <Button size="sm" disabled={!popId} onClick={() => setSel(`p:${popId}`)}>Open</Button>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
          {list.map((a) => (
            <button key={a.ref} onClick={() => setSel(a.ref)} className={cn("flex w-full items-center gap-2.5 rounded-md px-2 py-2 text-left", sel === a.ref ? "bg-raised" : "hover:bg-raised/60")}>
              <div className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-raised text-[11px] font-semibold text-muted">
                {initials(a.name)}<span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-panel" style={{ background: REGION_COLORS[a.region] }} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] font-medium">{a.name}</div>
                <div className="truncate text-xs text-muted">{a.kind === "stakeholder" ? a.persona.role : `${a.persona.age} · ${a.persona.city} · ${a.persona.stance}`}</div>
              </div>
              {a.opinion != null && <span className="num text-xs" style={{ color: scoreColor(a.opinion) }}>{fmt.s1(a.opinion)}</span>}
            </button>
          ))}
        </div>
      </div>
      {sel ? <Chat sim={sim} target={sel} key={sel} /> : <div className="card"><Empty title="Select an agent to interview" /></div>}
    </div>
  );
}

function Chat({ sim, target }: { sim: Simulation; target: string }) {
  const qc = useQueryClient();
  const d = useQuery({ queryKey: ["agent", sim.id, target], queryFn: () => api(`/simulations/${sim.id}/agents/${target}`) });
  const [msgs, setMsgs] = useState<{ role: string; content: string }[]>([]);
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { if (d.data?.chat) setMsgs(d.data.chat); }, [d.data]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs.length]);
  const send = useMutation({
    mutationFn: (m: string) => api(`/simulations/${sim.id}/agents/${target}/chat`, { json: { message: m } }),
    onMutate: (m) => setMsgs((x) => [...x, { role: "user", content: m }, { role: "assistant", content: "…" }]),
    onSuccess: (r) => { setMsgs(r.chat); qc.invalidateQueries({ queryKey: ["agent", sim.id, target] }); },
    onError: (e) => { setMsgs((x) => x.slice(0, -1)); toast.error(e instanceof ApiError ? e.message : "Failed"); },
  });
  const p = d.data?.persona || {};
  const op = d.data?.state?.opinion ?? d.data?.reaction?.score ?? d.data?.projected?.score;
  const suggestions = ["What made you score it that way?", "At what point did you lose interest?", "What would make you share this?", "How would your friends react?"];
  return (
    <div className="card flex min-h-0 flex-col">
      <div className="flex items-center gap-3 border-b border-line px-4 py-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-raised text-xs font-semibold text-muted" style={{ boxShadow: op != null ? `0 0 0 2px ${scoreColor(op)}` : undefined }}>{initials(d.data?.name)}</div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-semibold">{d.data?.name} <span className="font-normal text-muted">@{d.data?.handle}</span></div>
          <div className="truncate text-xs text-muted">{d.data?.kind === "stakeholder" ? p.description : `${p.age ?? ""} · ${p.gender ?? ""} · ${p.origin ?? ""} · ${p.city ?? ""} · ${p.profession ?? ""}`}</div>
        </div>
        {p.stance && <Badge><span className="h-1.5 w-1.5 rounded-full" style={{ background: STANCE_COLORS[p.stance] }} />{p.stance}</Badge>}
        {d.data?.kind === "population" && <Badge tone="outline">Projected</Badge>}
        {op != null && <span className="num text-lg font-semibold" style={{ color: scoreColor(op) }}>{fmt.s1(op)}</span>}
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {d.data?.reaction?.quote && <div className="border-l-2 border-line-strong pl-3 text-[13px] text-muted"><span className="font-medium text-fg">First reaction: </span>“{d.data.reaction.quote}”</div>}
        {msgs.length === 0 && <Suggestions items={suggestions} onPick={(s) => send.mutate(s)} />}
        {msgs.map((m, i) => (
          <div key={i} className={cn("max-w-[80%] rounded-lg px-3 py-2 text-[13px] leading-relaxed", m.role === "user" ? "ml-auto bg-brand-soft text-fg" : "border border-line bg-panel")}>
            {m.content === "…" ? <Loader2 className="h-4 w-4 animate-spin" /> : <span dir="auto" className="whitespace-pre-wrap">{m.content}</span>}
          </div>
        ))}
        <div ref={end} />
      </div>
      <form className="flex gap-2 border-t border-line p-3" onSubmit={(e) => { e.preventDefault(); if (text.trim()) { send.mutate(text.trim()); setText(""); } }}>
        <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask anything, in any language…" />
        <Button variant="primary" disabled={!text.trim() || send.isPending}><Send className="h-3.5 w-3.5" /></Button>
      </form>
    </div>
  );
}

function ReportChat({ sim }: { sim: Simulation }) {
  const hist = useQuery({ queryKey: ["report-chat", sim.id], queryFn: () => api<any[]>(`/simulations/${sim.id}/report/chat`) });
  const [msgs, setMsgs] = useState<{ role: string; content: string; meta?: any }[]>([]);
  const [text, setText] = useState("");
  useEffect(() => { if (hist.data) setMsgs(hist.data); }, [hist.data]);
  const send = useMutation({
    mutationFn: (m: string) => api(`/simulations/${sim.id}/report/chat`, { json: { message: m } }),
    onMutate: (m) => setMsgs((x) => [...x, { role: "user", content: m }, { role: "assistant", content: "…" }]),
    onSuccess: (r) => setMsgs((x) => [...x.slice(0, -1), { role: "assistant", content: r.answer, meta: { tools: r.tools } }]),
    onError: (e) => { setMsgs((x) => x.slice(0, -1)); toast.error(e instanceof ApiError ? e.message : "Failed"); },
  });
  if (sim.report_status !== "done") return <Callout tone="info">The analyst becomes available once the report is written.</Callout>;
  return (
    <div className="card mx-auto flex h-[calc(100vh-260px)] min-h-[520px] max-w-4xl flex-col">
      <div className="border-b border-line px-4 py-3"><div className="section-title">Analyst</div>
        <div className="mt-0.5 text-xs text-muted">Answers from the report first, then queries the graph, the population or agents when it needs new evidence.</div></div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
        {msgs.length === 0 && <Suggestions items={["Who should I target first and why?", "What one edit would most improve completion?", "How would Saudi women aged 25–34 react?", "What is the biggest risk?"]} onPick={(s) => send.mutate(s)} />}
        {msgs.map((m, i) => m.role === "user" ? (
          <div key={i} className="ml-auto max-w-[75%] rounded-lg bg-brand-soft px-3 py-2 text-[13px]">{m.content}</div>
        ) : (
          <div key={i} className="max-w-[90%]">
            {m.content === "…" ? <Loader2 className="h-4 w-4 animate-spin text-muted" /> : <div className="prose-report"><ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown></div>}
            {m.meta?.tools?.length > 0 && <div className="mt-1 text-xs text-muted">Sources queried: {m.meta.tools.map((t: any) => t.tool.replace(/_/g, " ")).join(", ")}</div>}
          </div>
        ))}
      </div>
      <form className="flex gap-2 border-t border-line p-3" onSubmit={(e) => { e.preventDefault(); if (text.trim()) { send.mutate(text.trim()); setText(""); } }}>
        <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask a follow-up about the results…" />
        <Button variant="primary" disabled={!text.trim() || send.isPending}><Send className="h-3.5 w-3.5" /></Button>
      </form>
    </div>
  );
}

function Surveys({ sim, stream }: { sim: Simulation; stream: StreamState }) {
  const list = useQuery({ queryKey: ["surveys", sim.id], queryFn: () => api<any[]>(`/simulations/${sim.id}/surveys`), refetchInterval: (q) => ((q.state.data as any[])?.some((s) => s.status === "running") ? 2500 : false) });
  const regions = sim.audience?.regions || [];
  const [f, setF] = useState({ question: "", region: "", stance: "", kind: "", n: 12 });
  const create = useMutation({
    mutationFn: () => api(`/simulations/${sim.id}/surveys`, { json: { question: f.question, region: f.region || null, stance: f.stance || null, kind: f.kind || null, n: f.n } }),
    onSuccess: () => { list.refetch(); setF({ ...f, question: "" }); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });
  return (
    <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
      <div className="card h-fit space-y-3 p-4">
        <div className="section-title">New survey</div>
        <Field label="Question"><Textarea value={f.question} onChange={(e) => setF({ ...f, question: e.target.value })} placeholder="Would you buy this product after seeing the ad? Why?" /></Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Region"><Select value={f.region || "*"} onChange={(v) => setF({ ...f, region: v === "*" ? "" : v })} options={[{ value: "*", label: "Any" }, ...regions.map((r: string) => ({ value: r, label: r }))]} /></Field>
          <Field label="Stance"><Select value={f.stance || "*"} onChange={(v) => setF({ ...f, stance: v === "*" ? "" : v })} options={[{ value: "*", label: "Any" }, ...["enthusiast", "neutral", "skeptic", "contrarian", "disengaged"].map((s) => ({ value: s, label: s }))]} /></Field>
          <Field label="Who"><Select value={f.kind || "*"} onChange={(v) => setF({ ...f, kind: v === "*" ? "" : v })} options={[{ value: "*", label: "Everyone" }, { value: "voice", label: "People" }, { value: "stakeholder", label: "Accounts" }]} /></Field>
          <Field label="Respondents"><Input type="number" min={1} max={40} value={f.n} onChange={(e) => setF({ ...f, n: Number(e.target.value) })} /></Field>
        </div>
        <Button variant="primary" className="w-full" disabled={f.question.trim().length < 3} loading={create.isPending} onClick={() => create.mutate()}>Run survey</Button>
      </div>
      <div className="space-y-4">
        {(list.data || []).length === 0 && <div className="card"><Empty title="No surveys yet">Ask a whole segment the same question and get themed, quotable answers.</Empty></div>}
        {(list.data || []).map((s) => {
          const live = stream.surveyAnswers[s.id] || [];
          const answers = s.status === "done" ? s.answers : live;
          return (
            <div key={s.id} className="card p-4">
              <div className="flex items-start justify-between gap-3">
                <div><div className="text-[13px] font-semibold">{s.question}</div>
                  <div className="mt-1 flex gap-1">{Object.entries(s.filters).filter(([, v]) => v).map(([k, v]: any) => <Badge key={k} tone="outline">{k}: {String(v)}</Badge>)}</div></div>
                <Status tone={s.status === "done" ? "pos" : s.status === "failed" ? "neg" : "brand"}>{s.status === "running" ? `${answers.length} answers so far` : s.status === "done" ? "Complete" : s.status}</Status>
              </div>
              {s.summary?.themes?.length > 0 && (
                <div className="mt-3 grid grid-cols-2 gap-2">
                  {s.summary.themes.map((t: any, i: number) => <div key={i} className="rounded-md border border-line p-2.5 text-xs"><div className="flex justify-between font-medium"><span>{t.theme}</span><span className="num text-muted">{t.count}</span></div>
                    <div className="mt-1 text-muted">“{t.quote}”</div></div>)}
                </div>
              )}
              {s.summary?.takeaway && <Callout tone="brand" className="mt-3">{s.summary.takeaway}</Callout>}
              <div className="mt-3 max-h-72 space-y-1.5 overflow-y-auto">
                {answers.map((a: any, i: number) => (
                  <div key={i} className="flex gap-2 text-xs"><span className="h-1.5 w-1.5 mt-1.5 shrink-0 rounded-full" style={{ background: STANCE_COLORS[a.stance] || "#94a3b8" }} />
                    <span className="w-32 shrink-0 truncate font-medium">{a.name}</span><span dir="auto" className="text-muted">{a.answer}</span></div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Suggestions({ items, onPick }: { items: string[]; onPick: (s: string) => void }) {
  return (
    <div>
      <div className="mb-1.5 text-xs font-medium text-muted">Suggested questions</div>
      <div className="divide-y divide-line overflow-hidden rounded-md border border-line">
        {items.map((s) => <button key={s} onClick={() => onPick(s)} className="block w-full px-3 py-2 text-left text-[13px] hover:bg-raised">{s}</button>)}
      </div>
    </div>
  );
}