import { Link } from "react-router-dom";
import { fmt } from "@/lib/utils";

export type MemoryDetail = {
  fresh?: boolean;
  affinity?: { familiarity: number; affinity: number; fatigue: number } | null;
  memories: { id: string; text: string; kind: string; importance: number; created_at: string; source_simulation_id: string | null }[];
};

export function AgentMemories({ data }: { data?: MemoryDetail }) {
  if (!data) return null;
  return <details className="rounded-md border border-line p-3 text-xs">
    <summary className="cursor-pointer font-medium">Remembers · {data.memories.length} simulated memories</summary>
    <p className="mt-2 text-muted">Synthetic experiences, never real follower data.{data.fresh ? " Memory was ignored for this fresh-audience test." : ""}</p>
    {data.affinity && <p className="mt-2 text-muted">Familiarity {data.affinity.familiarity.toFixed(1)} · Affinity {data.affinity.affinity.toFixed(2)} · Fatigue {fmt.pct(data.affinity.fatigue)}</p>}
    {!data.memories.length && <p className="mt-2 text-muted">No retained simulated memories yet.</p>}
    <ol className="mt-2 max-h-64 space-y-2 overflow-y-auto">
      {data.memories.map((m) => <li key={m.id} className="border-t border-line pt-2">
        <p>{m.text}</p><p className="mt-1 text-faint">{new Date(m.created_at).toLocaleDateString()} · Importance {fmt.pct(m.importance)} · {m.kind}
          {m.source_simulation_id && <> · <Link to={`/simulations/${m.source_simulation_id}`} className="text-brand">Source run</Link></>}</p>
      </li>)}
    </ol>
  </details>;
}
