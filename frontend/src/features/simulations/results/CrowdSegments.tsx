import { Card } from "@/components/ui/primitives";
import { scoreColor } from "@/lib/colors";
import { fmt } from "@/lib/utils";

/** The groups the creator named in the crowd chat ("the skeptics", "the fans"), side by side. */
export function CrowdSegments({ segments, brief, onAgent }: { segments?: any[]; brief?: string; onAgent: (ref: string) => void }) {
  if (!segments?.length) return null;
  const note = segments.find((s) => s.note)?.note;
  return (
    <Card className="p-5" aria-label="Your segments">
      <h2 className="font-semibold">Your segments</h2>
      <p className="mt-0.5 text-xs text-muted">{note || "The groups you asked to compare."}{brief ? ` Crowd: “${brief.length > 140 ? brief.slice(0, 140) + "…" : brief}”` : ""}</p>
      <div className="mt-4 space-y-4">
        {segments.map((s) => (
          <div key={s.name}>
            <div className="flex items-baseline justify-between gap-3">
              <span className="min-w-0"><span className="text-[13px] font-medium">{s.name}</span>{s.description && <span className="ml-1.5 text-xs text-muted">{s.description}</span>}</span>
              <span className="num shrink-0 text-lg" style={{ color: s.score != null ? scoreColor(s.score) : undefined }}>{s.score != null ? s.score.toFixed(1) : "–"}</span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-raised">
              {s.score != null && <div className="h-full rounded-full" style={{ width: `${s.score * 10}%`, background: scoreColor(s.score) }} />}
            </div>
            <div className="mt-1 text-2xs text-muted">
              {s.n ? `${fmt.pct(s.share_of_audience, 1)} of audience · ${s.voice_n} interviewed${s.would_share != null ? ` · share ${fmt.pct(s.would_share)}` : ""}` : "Nobody in your crowd fits this group."}
              {s.voice_n === 0 && s.n > 0 ? " · projected only, nobody interviewed" : ""}
            </div>
            {s.objection && <div className="mt-1 text-2xs"><span className="text-faint">Objection:</span> {s.objection}</div>}
            {s.evidence && <button onClick={() => onAgent(s.evidence.agent)} className="mt-1.5 block border-l-2 border-line-strong pl-2.5 text-left text-xs text-muted hover:text-fg">“{s.evidence.quote}” <span className="text-[11px] text-faint">· {s.evidence.name}</span></button>}
          </div>
        ))}
      </div>
    </Card>
  );
}
