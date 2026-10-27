import { ArrowUp, RotateCcw, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { useReference } from "@/lib/queries";
import { cn } from "@/lib/utils";

/** Fields the crowd chat owns; resetting clears these and keeps the rest (creator split, "match my audience"). */
export const CROWD_DEFAULTS = { regions: ["AE", "SA", "EG", "JO", "MA"], age_min: 16, age_max: 70, genders: [], platforms: [], citizens_only: false,
  expats_only: false, interests: [], professions: [], incomes: [], stances: [], education_min: null, emirates: [], nationality_groups: [],
  income_bands: [], languages: [], ocean: {}, brief: "" };

const EXAMPLES = [
  "Gen Z gamers in Riyadh who mostly watch on TikTok and roll their eyes at sponsored posts",
  "Night-shift nurses in Dubai who scroll on breaks and love wholesome content",
  "Skeptical Egyptian dads, 35-50, into football and money talk",
];

interface Msg { role: "user" | "assistant"; text: string }

export function CrowdChat({ value, onChange }: { value: any; onChange: (v: any) => void }) {
  const ref = useReference();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const log = useRef<HTMLDivElement>(null);
  useEffect(() => { log.current?.scrollTo({ top: log.current.scrollHeight }); }, [msgs, busy]);

  async function send(text = draft) {
    const message = text.trim();
    if (!message || busy) return;
    setMsgs((m) => [...m, { role: "user", text: message }]);
    setDraft("");
    setBusy(true);
    try {
      const out = await api<{ audience: any; reply: string }>("/datapool/population/crowd", { json: { message, audience: clean(value) } });
      onChange({ ...value, ...out.audience });
      setMsgs((m) => [...m, { role: "assistant", text: out.reply }]);
    } catch (e) {
      setMsgs((m) => m.slice(0, -1));
      setDraft(message);
      toast.error(e instanceof ApiError ? e.message : "Could not update the crowd");
    } finally { setBusy(false); }
  }

  const regionName = (c: string) => ref.data?.regions.find((r) => r.code === c)?.short || ref.data?.emirates.find((e) => e.code === c)?.name || c;
  const interest = (k: string) => ref.data?.interests.find((i) => i.key === k)?.label || k;
  const drop = (patch: Record<string, unknown>) => onChange({ ...value, ...patch });
  const without = (k: string, v: string) => drop({ [k]: value[k].filter((x: string) => x !== v) });
  const chips: { label: ReactNode; clear?: () => void }[] = [
    ...(value.regions || []).map((c: string) => ({ label: regionName(c), clear: value.regions.length > 1 ? () => without("regions", c) : undefined })),
    ...((value.age_min || 16) > 16 || (value.age_max || 70) < 70 ? [{ label: `Ages ${value.age_min || 16}–${value.age_max || 70}`, clear: () => drop({ age_min: 16, age_max: 70 }) }] : []),
    ...(value.genders?.length === 1 ? [{ label: value.genders[0] === "female" ? "Women" : "Men", clear: () => drop({ genders: [] }) }] : []),
    ...(value.citizens_only ? [{ label: "Citizens", clear: () => drop({ citizens_only: false }) }] : []),
    ...(value.expats_only ? [{ label: "Expatriates", clear: () => drop({ expats_only: false }) }] : []),
    ...(value.interests || []).map((k: string) => ({ label: interest(k), clear: () => without("interests", k) })),
    ...(value.platforms || []).map((k: string) => ({ label: `On ${ref.data?.platforms.find((p) => p.key === k)?.label || k}`, clear: () => without("platforms", k) })),
    ...["professions", "incomes", "stances", "nationality_groups", "income_bands", "languages", "emirates"].flatMap((k) =>
      (value[k] || []).filter((v: string) => k !== "emirates" || !value.regions?.includes(v)).map((v: string) => ({ label: k === "incomes" ? `${v} income` : k === "emirates" ? regionName(v) : v, clear: () => without(k, v) }))),
    ...Object.entries(value.ocean || {}).map(([t, r]: any) => ({ label: `${t} ${r[0].toFixed(1)}–${r[1].toFixed(1)}`, clear: () => { const o = { ...value.ocean }; delete o[t]; drop({ ocean: o }); } })),
  ];

  return (
    <div className="overflow-hidden rounded-md border border-line">
      <div ref={log} className="max-h-[320px] space-y-2.5 overflow-y-auto bg-raised/40 p-3" aria-live="polite">
        <Bubble role="assistant">Describe the crowd you want in your own words: who they are, where they live, what they care about, how they scroll. Be as specific or as strange as you like. Keep chatting to refine it.</Bubble>
        {!msgs.length && !value.brief && (
          <div className="flex flex-wrap gap-1.5 pl-1">
            {EXAMPLES.map((x) => <button key={x} type="button" onClick={() => send(x)} className="rounded-full border border-line-strong bg-panel px-2.5 py-1 text-left text-xs text-muted hover:text-fg">{x}</button>)}
          </div>
        )}
        {msgs.map((m, i) => <Bubble key={i} role={m.role}>{m.text}</Bubble>)}
        {busy && <Bubble role="assistant"><span className="text-muted">Shaping your crowd…</span></Bubble>}
      </div>
      <form className="flex items-end gap-2 border-t border-line bg-panel p-2" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <Textarea aria-label="Describe your crowd" value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={2000} rows={1}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          className="min-h-[38px] flex-1 resize-none border-0 shadow-none focus-visible:ring-0" placeholder={msgs.length ? "Refine it: add, remove or change anything…" : "e.g. Moroccan students who love anime and argue in the comments"} />
        <Button type="submit" variant="primary" size="icon" aria-label="Send" loading={busy} disabled={!draft.trim()}>{!busy && <ArrowUp className="h-4 w-4" />}</Button>
      </form>
      <div className="space-y-2 border-t border-line px-3 py-2.5">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-medium text-muted">Your crowd</span>
          <Button size="sm" variant="ghost" onClick={() => { onChange({ ...value, ...CROWD_DEFAULTS }); setMsgs([]); }}><RotateCcw className="h-3 w-3" />Start over</Button>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {chips.map((c, i) => (
            <span key={i} className="inline-flex h-6 items-center gap-1 rounded-md border border-line-strong bg-panel px-2 text-xs">
              {c.label}{c.clear && <button type="button" aria-label="Remove" onClick={c.clear} className="text-muted hover:text-fg"><X className="h-3 w-3" /></button>}
            </span>
          ))}
          {chips.length <= (value.regions?.length || 0) && <span className="text-xs text-muted">Everyone in these places, any age.</span>}
        </div>
        {value.brief && (
          <div className="flex items-start gap-2 rounded-md bg-brand-soft/50 px-2.5 py-2 text-xs leading-relaxed">
            <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand" />
            <span className="min-w-0 flex-1"><span className="font-medium">Every agent reads:</span> {value.brief}</span>
            <button type="button" aria-label="Clear description" onClick={() => drop({ brief: "" })} className="text-muted hover:text-fg"><X className="h-3 w-3" /></button>
          </div>
        )}
      </div>
    </div>
  );
}

function Bubble({ role, children }: { role: Msg["role"]; children: ReactNode }) {
  return (
    <div className={cn("flex", role === "user" && "justify-end")}>
      <div className={cn("max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-[13px] leading-relaxed",
        role === "user" ? "bg-brand text-brand-fg" : "border border-line bg-panel")}>{children}</div>
    </div>
  );
}

function clean(a: any) {
  return { ...a, age_min: a.age_min || null, age_max: a.age_max || null };
}
