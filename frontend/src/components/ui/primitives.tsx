import * as RSwitch from "@radix-ui/react-switch";
import * as RSlider from "@radix-ui/react-slider";
import * as RTabs from "@radix-ui/react-tabs";
import * as RTooltip from "@radix-ui/react-tooltip";
import { Check, HelpCircle, Minus } from "lucide-react";
import { createContext, forwardRef, useContext, useId, type HTMLAttributes, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("card", className)} {...p} />;
}

export function CardHeader({ title, subtitle, actions, className, divider }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; className?: string; divider?: boolean }) {
  return (
    <div className={cn("flex items-start justify-between gap-3 px-4 py-3", divider && "border-b border-line", className)}>
      <div className="min-w-0">
        <div className="section-title">{title}</div>
        {subtitle && <div className="mt-0.5 text-xs text-muted">{subtitle}</div>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

/** Section heading inside a panel: sentence case, no decoration. */
export function SectionHeader({ title, actions, sub, className }: { title: ReactNode; actions?: ReactNode; sub?: ReactNode; className?: string }) {
  return (
    <div className={cn("mb-2.5 flex items-end justify-between gap-3", className)}>
      <div className="min-w-0">
        <h3 className="section-title">{title}</h3>
        {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

const field = "w-full rounded-md border border-line-strong bg-panel text-[13px] text-fg placeholder:text-faint shadow-[inset_0_1px_1px_rgb(16_24_40/0.03)] focus:border-brand focus:outline-none focus:ring-[3px] focus:ring-brand/15 disabled:bg-raised disabled:opacity-70";

const FieldLabelContext = createContext<string | undefined>(undefined);
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className, ...p }, ref) => {
  const labelId = useContext(FieldLabelContext);
  return <input ref={ref} aria-labelledby={p["aria-label"] ? undefined : labelId} className={cn(field, "h-8 px-2.5", className)} {...p} />;
});
Input.displayName = "Input";

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...p }, ref) => {
  const labelId = useContext(FieldLabelContext);
  return <textarea ref={ref} aria-labelledby={p["aria-label"] ? undefined : labelId} className={cn(field, "min-h-[96px] resize-y px-2.5 py-2 leading-relaxed", className)} {...p} />;
});
Textarea.displayName = "Textarea";

export function Label({ children, hint, className, id }: { children: ReactNode; hint?: ReactNode; className?: string; id?: string }) {
  return (
    <div className={cn("mb-1.5 flex items-baseline justify-between gap-2", className)}>
      <label id={id} className="text-[13px] font-medium text-fg">{children}</label>
      {hint && <span className="text-xs text-faint">{hint}</span>}
    </div>
  );
}

export function Field({ label, hint, help, children, className }: { label: ReactNode; hint?: ReactNode; help?: ReactNode; children: ReactNode; className?: string }) {
  const labelId = useId();
  return (
    <div className={className}>
      <Label hint={hint} id={labelId}>{label}</Label>
      <FieldLabelContext.Provider value={labelId}>{children}</FieldLabelContext.Provider>
      {help && <div className="mt-1.5 text-xs leading-relaxed text-muted">{help}</div>}
    </div>
  );
}

export function Badge({ children, tone = "default", className }: { children: ReactNode; tone?: "default" | "brand" | "pos" | "neg" | "warn" | "info" | "outline"; className?: string }) {
  const tones = {
    default: "bg-raised text-muted border-line",
    brand: "bg-brand-soft text-brand border-brand/20",
    pos: "bg-pos/[0.08] text-pos border-pos/20",
    neg: "bg-neg/[0.08] text-neg border-neg/20",
    warn: "bg-warn/[0.08] text-warn border-warn/25",
    info: "bg-brand-soft text-brand border-brand/20",
    outline: "bg-transparent text-muted border-line-strong",
  };
  return <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-sm border px-1.5 py-px text-2xs font-medium", tones[tone], className)}>{children}</span>;
}

/** Status text with a small coloured square, used in tables instead of loud badges. */
export function Status({ tone = "default", children }: { tone?: "default" | "brand" | "pos" | "neg" | "warn" | "info"; children: ReactNode }) {
  const c = { default: "bg-faint", brand: "bg-brand", pos: "bg-pos", neg: "bg-neg", warn: "bg-warn", info: "bg-brand" }[tone];
  return <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-[13px]"><span className={cn("h-2 w-2 rounded-[2px]", c)} />{children}</span>;
}

export function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label?: ReactNode; disabled?: boolean }) {
  return (
    <label className={cn("inline-flex cursor-pointer items-center gap-2 text-[13px]", disabled && "cursor-not-allowed opacity-50")}>
      <RSwitch.Root checked={checked} onCheckedChange={onChange} disabled={disabled}
        className="relative h-[18px] w-[30px] shrink-0 rounded-full bg-line-strong transition-colors data-[state=checked]:bg-brand">
        <RSwitch.Thumb className="block h-[14px] w-[14px] translate-x-[2px] rounded-full bg-white shadow-sm transition-transform data-[state=checked]:translate-x-[14px]" />
      </RSwitch.Root>
      {label}
    </label>
  );
}

export function Checkbox({ checked, onChange, indeterminate, disabled }: { checked: boolean; onChange?: (v: boolean) => void; indeterminate?: boolean; disabled?: boolean }) {
  return (
    <button type="button" role="checkbox" aria-checked={indeterminate ? "mixed" : checked} disabled={disabled}
      onClick={(e) => { e.stopPropagation(); onChange?.(!checked); }}
      className={cn("flex h-4 w-4 shrink-0 items-center justify-center rounded-[4px] border transition-colors",
        checked || indeterminate ? "border-brand bg-brand text-white" : "border-line-strong bg-panel hover:border-faint", disabled && "opacity-50")}>
      {indeterminate ? <Minus className="h-3 w-3" strokeWidth={3} /> : checked ? <Check className="h-3 w-3" strokeWidth={3} /> : null}
    </button>
  );
}

/** A labelled checkbox row, with an optional right-aligned figure (e.g. a count). */
export function CheckRow({ checked, onChange, label, meta, sub }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; meta?: ReactNode; sub?: ReactNode }) {
  return (
    <label className="flex cursor-pointer items-center gap-2.5 rounded px-1.5 py-1 hover:bg-raised" onClick={() => onChange(!checked)}>
      <Checkbox checked={checked} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] text-fg">{label}</span>
        {sub && <span className="block truncate text-xs text-muted">{sub}</span>}
      </span>
      {meta != null && <span className="num shrink-0 text-xs text-muted">{meta}</span>}
    </label>
  );
}

export function Slider({ value, onChange, min, max, step = 1, className }: { value: number; onChange: (v: number) => void; min: number; max: number; step?: number; className?: string }) {
  return (
    <RSlider.Root className={cn("relative flex h-5 w-full touch-none select-none items-center", className)} value={[value]} min={min} max={max} step={step}
      onValueChange={(v) => onChange(v[0])}>
      <RSlider.Track className="relative h-[3px] w-full grow overflow-hidden rounded-full bg-line-strong/70">
        <RSlider.Range className="absolute h-full bg-brand" />
      </RSlider.Track>
      <RSlider.Thumb className="block h-4 w-4 rounded-full border border-line-strong bg-panel shadow-sm focus:outline-none focus:ring-[3px] focus:ring-brand/20" />
    </RSlider.Root>
  );
}

export function RangeSlider({ value, onChange, min = 0, max = 1, step = 0.05, className }: { value: [number, number]; onChange: (v: [number, number]) => void; min?: number; max?: number; step?: number; className?: string }) {
  return (
    <RSlider.Root className={cn("relative flex h-5 w-full touch-none select-none items-center", className)} value={value} min={min} max={max} step={step}
      minStepsBetweenThumbs={1} onValueChange={(v) => onChange([v[0], v[1]])}>
      <RSlider.Track className="relative h-[3px] w-full grow overflow-hidden rounded-full bg-line-strong/70">
        <RSlider.Range className="absolute h-full bg-brand" />
      </RSlider.Track>
      {[0, 1].map((i) => <RSlider.Thumb key={i} className="block h-4 w-4 rounded-full border border-line-strong bg-panel shadow-sm focus:outline-none focus:ring-[3px] focus:ring-brand/20" />)}
    </RSlider.Root>
  );
}

/** Plain-language definitions for the product's terms, shown wherever the term appears. */
export const GLOSSARY: Record<string, string> = {
  voice: "Voice agents are a sample of the audience played by a language model. Each one reacts in character, posts, comments and changes its mind.",
  crowd: "Crowd agents act through a fast statistical model: they see posts, like, repost and drift toward what their feed shows. They add scale and spread.",
  stakeholder: "Stakeholder accounts are brands, media and public figures from the knowledge graph that join the conversation as accounts.",
  population: "One million synthetic people with realistic demographics, personalities, interests and follower networks for each region.",
  opinion: "Projected opinion: how much the audience likes the content on a 0 to 10 scale after seeing it and the conversation around it. 5 means fine, kept scrolling.",
  completion: "Completion: the share of the audience still paying attention at the end.",
  viral: "Viral potential: a 1 to 10 score from six factors (emotional pull, shareability, novelty, controversy, appeal to large accounts, fit with current trends).",
  reach: "Reach: how many people see it as it is shared through the follower network, simulated several times.",
  interval: "The 95% interval is the range the true average most likely falls in, given the sample of interviewed agents.",
  echo: "Echo chamber: how strongly the feed shows people posts that agree with them.",
  graph: "The knowledge graph links the content to the people, brands, places and live news it relates to. Agents use it for context.",
  live: "Live context: this hour's weather, headlines, news mood, holidays and social trends for each region. Agents react as if it were that moment.",
  benchmark: "Percentile among all simulations on Kruvim in the same niche. Only anonymous aggregates are used.",
};

export function InfoTip({ term, text, className }: { term?: keyof typeof GLOSSARY | string; text?: ReactNode; className?: string }) {
  const content = text ?? (term ? GLOSSARY[term] : null);
  if (!content) return null;
  return (
    <Tip content={content}>
      <button type="button" aria-label="What does this mean?" className={cn("inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-faint hover:text-fg", className)}>
        <HelpCircle className="h-3.5 w-3.5" />
      </button>
    </Tip>
  );
}

export const Tabs = RTabs.Root;
export function TabsList({ className, ...p }: RTabs.TabsListProps) {
  return <RTabs.List className={cn("inline-flex items-center gap-0.5 rounded-md border border-line bg-raised p-0.5", className)} {...p} />;
}
export function TabsTrigger({ className, ...p }: RTabs.TabsTriggerProps) {
  return <RTabs.Trigger className={cn("rounded-[4px] px-2.5 py-1 text-xs font-medium text-muted transition-colors hover:text-fg data-[state=active]:bg-panel data-[state=active]:text-fg data-[state=active]:shadow-sm", className)} {...p} />;
}
export const TabsContent = RTabs.Content;

export function UnderlineTabs({ tabs, value, onChange, className }: { tabs: { key: string; label: ReactNode; badge?: ReactNode }[]; value: string; onChange: (k: string) => void; className?: string }) {
  return (
    <div className={cn("flex items-center gap-6 overflow-x-auto border-b border-line", className)}>
      {tabs.map((t) => (
        <button key={t.key} onClick={() => onChange(t.key)}
          className={cn("relative -mb-px flex shrink-0 items-center gap-1.5 border-b-2 py-2.5 text-[13px] font-medium transition-colors",
            value === t.key ? "border-brand text-fg" : "border-transparent text-muted hover:text-fg")}>
          {t.label}
          {t.badge}
        </button>
      ))}
    </div>
  );
}

export function Segmented<T extends string>({ options, value, onChange, size = "sm" }: { options: { value: T; label: ReactNode }[]; value: T; onChange: (v: T) => void; size?: "sm" | "md" }) {
  return (
    <div className="inline-flex rounded-md border border-line-strong bg-panel p-0.5">
      {options.map((o) => (
        <button key={o.value} onClick={() => onChange(o.value)}
          className={cn("rounded-[4px] font-medium transition-colors", size === "sm" ? "px-2 py-0.5 text-xs" : "px-3 py-1 text-[13px]",
            value === o.value ? "bg-raised text-fg shadow-[inset_0_0_0_1px_rgb(var(--line-strong))]" : "text-muted hover:text-fg")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Tip({ content, children, side = "top" }: { content: ReactNode; children: ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  return (
    <RTooltip.Root delayDuration={200}>
      <RTooltip.Trigger asChild>{children}</RTooltip.Trigger>
      <RTooltip.Portal>
        <RTooltip.Content side={side} sideOffset={6} className="z-50 max-w-xs rounded-md bg-[#111827] px-2.5 py-1.5 text-xs text-white shadow-pop animate-fade-in">
          {content}
        </RTooltip.Content>
      </RTooltip.Portal>
    </RTooltip.Root>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton h-4", className)} />;
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      {icon && <div className="mb-3 text-faint">{icon}</div>}
      <div className="text-sm font-medium">{title}</div>
      {children && <div className="mt-1 max-w-md text-[13px] leading-relaxed text-muted">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Stat({ label, value, sub, accent, className }: { label: ReactNode; value: ReactNode; sub?: ReactNode; accent?: string; className?: string }) {
  return (
    <div className={cn("min-w-0", className)}>
      <div className="truncate text-xs font-medium text-muted">{label}</div>
      <div className="num mt-1 flex items-center gap-2 text-[22px] font-semibold leading-tight tracking-[-0.01em]">
        {accent && <span className="h-2.5 w-2.5 shrink-0 rounded-[2px]" style={{ background: accent }} aria-hidden />}{value}
      </div>
      {sub && <div className="mt-0.5 truncate text-xs text-muted">{sub}</div>}
    </div>
  );
}

/** Key/value rows for metadata panels. */
export function KV({ rows, className }: { rows: [ReactNode, ReactNode][]; className?: string }) {
  return (
    <dl className={cn("divide-y divide-line text-[13px]", className)}>
      {rows.map(([k, v], i) => (
        <div key={i} className="flex items-baseline justify-between gap-4 py-1.5">
          <dt className="shrink-0 text-muted">{k}</dt>
          <dd className="num min-w-0 truncate text-right text-fg">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Progress({ value, className, tone = "brand" }: { value: number; className?: string; tone?: "brand" | "warn" | "neg" }) {
  const c = { brand: "bg-brand", warn: "bg-warn", neg: "bg-neg" }[tone];
  return (
    <div className={cn("h-1 w-full overflow-hidden rounded-full bg-line", className)}>
      <div className={cn("h-full rounded-full transition-[width] duration-500", c)} style={{ width: `${Math.max(0, Math.min(100, value * 100))}%` }} />
    </div>
  );
}

export function Bar({ value, max = 1, color, className }: { value: number; max?: number; color?: string; className?: string }) {
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-sm bg-line/80", className)}>
      <div className="h-full rounded-sm" style={{ width: `${Math.max(0, Math.min(1, (value || 0) / (max || 1))) * 100}%`, background: color || "rgb(var(--brand))" }} />
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="mono rounded border border-line bg-raised px-1 text-2xs text-muted">{children}</kbd>;
}

/** Toggle button used for compact multi-select filters. */
export function Chip({ active, onClick, children, count }: { active?: boolean; onClick?: () => void; children: ReactNode; count?: ReactNode }) {
  return (
    <button onClick={onClick}
      className={cn("inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-xs transition-colors",
        active ? "border-brand/50 bg-brand-soft text-brand" : "border-line-strong bg-panel text-muted hover:text-fg")}>
      {active && <Check className="h-3 w-3" strokeWidth={2.5} />}
      {children}
      {count != null && <span className="num text-2xs opacity-70">{count}</span>}
    </button>
  );
}

export function Callout({ tone = "info", title, children, className, action }: { tone?: "info" | "warn" | "neg" | "brand"; title?: ReactNode; children: ReactNode; className?: string; action?: ReactNode }) {
  const t = { info: "border-l-brand", warn: "border-l-warn", neg: "border-l-neg", brand: "border-l-brand" }[tone];
  return (
    <div className={cn("flex items-start gap-4 rounded-md border border-line border-l-[3px] bg-panel px-3.5 py-2.5 text-[13px] leading-relaxed", t, className)}>
      <div className="min-w-0 flex-1">
        {title && <div className="font-medium text-fg">{title}</div>}
        <div className="text-muted">{children}</div>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
