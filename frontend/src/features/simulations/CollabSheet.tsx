import { useQuery } from "@tanstack/react-query";
import { Check, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Select, Sheet, SheetClose } from "@/components/ui/overlay";
import { Status, Textarea, UnderlineTabs } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { can, useAuth } from "@/lib/auth";
import { scoreColor } from "@/lib/colors";
import type { Simulation } from "@/lib/types";
import { cn, fmt } from "@/lib/utils";

export const REVIEW: Record<string, { label: string; tone: "default" | "brand" | "pos" | "warn" }> = {
  none: { label: "Not reviewed", tone: "default" }, in_review: { label: "In review", tone: "brand" },
  approved: { label: "Approved", tone: "pos" }, changes_requested: { label: "Changes requested", tone: "warn" },
};

function anchorLabel(a: string, sim: Simulation) {
  if (a === "general") return "General";
  if (a === "review") return "Review";
  const [k, v] = a.split(":");
  if (k === "segment") {
    const s = sim.card?.segments?.[Number(v)];
    return `Moment ${Number(v) + 1}${s?.start != null && sim.card?.timed ? ` (${fmt.t(s.start)})` : ""}${s?.label ? `: ${s.label}` : ""}`;
  }
  return `${k[0].toUpperCase()}${k.slice(1)} ${v}`;
}

export function CollabSheet({ sim, open, tab, anchor, onClose, onChanged }: {
  sim: Simulation; open: boolean; tab: "comments" | "versions"; anchor: string; onClose: () => void; onChanged: () => void;
}) {
  const nav = useNavigate();
  const me = useAuth((s) => s.user);
  const [t, setT] = useState(tab);
  const [body, setBody] = useState("");
  const [at, setAt] = useState(anchor);
  useEffect(() => { setT(tab); setAt(anchor); }, [tab, anchor, open]);
  const notes = useQuery({ queryKey: ["annotations", sim.id], queryFn: () => api<any[]>(`/simulations/${sim.id}/annotations`), enabled: open });
  const versions = useQuery({ queryKey: ["versions", sim.id], queryFn: () => api<any[]>(`/simulations/${sim.id}/versions`), enabled: open && t === "versions" });
  const segs: any[] = sim.card?.segments || [];

  async function add() {
    try {
      await api(`/simulations/${sim.id}/annotations`, { json: { anchor: at, body } });
      setBody(""); notes.refetch(); onChanged();
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not add the comment"); }
  }
  async function patch(id: string, json: any) { await api(`/annotations/${id}`, { method: "PATCH", json }); notes.refetch(); }
  async function del(id: string) { await api(`/annotations/${id}`, { method: "DELETE" }); notes.refetch(); onChanged(); }

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()} width={500}>
      <div className="flex items-center justify-between border-b border-line px-5 py-3">
        <div className="section-title">Team</div>
        <SheetClose className="rounded p-1 text-muted hover:bg-raised hover:text-fg" aria-label="Close"><X className="h-4 w-4" /></SheetClose>
      </div>
      <UnderlineTabs className="px-5" value={t} onChange={(k) => setT(k as typeof t)} tabs={[{ key: "comments", label: `Comments${notes.data?.length ? ` (${notes.data.length})` : ""}` }, { key: "versions", label: "Version history" }]} />
      {t === "comments" ? (
        <>
          <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
            {(notes.data || []).length === 0 && <p className="text-[13px] text-muted">No comments yet. Pin notes to moments in the attention heatmap, or leave general feedback for the team.</p>}
            {(notes.data || []).map((n) => (
              <div key={n.id} className={cn("rounded-md border border-line px-3 py-2.5", n.resolved && "opacity-60")}>
                <div className="flex items-center gap-2 text-xs">
                  <span className="font-medium">{n.author}</span><span className="text-muted">· {anchorLabel(n.anchor, sim)} · {fmt.ago(n.created_at)}</span>
                  <span className="ml-auto flex gap-1">
                    <button title={n.resolved ? "Reopen" : "Resolve"} onClick={() => patch(n.id, { resolved: !n.resolved })} className="rounded p-1 text-muted hover:bg-raised hover:text-fg"><Check className="h-3.5 w-3.5" /></button>
                    {(n.user_id === me?.id || can("admin")) && <button title="Delete" onClick={() => del(n.id)} className="rounded p-1 text-muted hover:bg-raised hover:text-neg"><Trash2 className="h-3.5 w-3.5" /></button>}
                  </span>
                </div>
                <p className="mt-1 whitespace-pre-wrap text-[13px] leading-relaxed">{n.body}</p>
              </div>
            ))}
          </div>
          {can("member") && (
            <div className="space-y-2 border-t border-line px-5 py-3">
              <Select value={at} onChange={setAt} options={[{ value: "general", label: "General comment" },
                ...segs.map((s, i) => ({ value: `segment:${i}`, label: anchorLabel(`segment:${i}`, sim) }))]} />
              <Textarea value={body} onChange={(e) => setBody(e.target.value)} className="min-h-[72px]" placeholder="Write a comment for your team" />
              <div className="flex justify-end"><Button variant="primary" size="sm" disabled={!body.trim()} onClick={add}>Comment</Button></div>
            </div>
          )}
        </>
      ) : (
        <div className="flex-1 overflow-y-auto">
          <p className="px-5 pt-4 text-[13px] text-muted">Every re-test and re-run of this content, oldest first. Scores show whether each edit helped.</p>
          <table className="dt mt-3">
            <thead><tr><th>Version</th><th>Status</th><th className="!text-right">Opinion</th></tr></thead>
            <tbody>{(versions.data || []).map((v, i, arr) => {
              const prev = arr.slice(0, i).reverse().find((x) => x.score != null);
              const d = v.score != null && prev ? v.score - prev.score : null;
              return (
                <tr key={v.id} className={cn("hoverable", v.current && "bg-brand-soft/40")} onClick={() => { onClose(); nav(`/simulations/${v.id}`); }}>
                  <td><div className="font-medium">{v.name}</div><div className="text-xs text-muted">{fmt.date(v.created_at)}{v.current ? " · this run" : ""}</div></td>
                  <td className="text-xs capitalize text-muted">{v.status.replace("_", " ")}</td>
                  <td className="r">{v.score != null ? <span><span className="mr-1.5 inline-block h-2 w-2 rounded-[2px]" style={{ background: scoreColor(v.score) }} />{v.score.toFixed(2)}
                    {d != null && <span className={cn("ml-1.5 text-xs", d >= 0 ? "text-pos" : "text-neg")}>{d >= 0 ? "+" : ""}{d.toFixed(2)}</span>}</span> : "–"}</td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      )}
    </Sheet>
  );
}

export function ReviewStatus({ status }: { status?: string }) {
  const r = REVIEW[status || "none"];
  return <Status tone={r.tone}>{r.label}</Status>;
}
