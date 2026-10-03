import { useNavigate } from "react-router-dom";
import { Progress, Status } from "@/components/ui/primitives";
import { scoreColor } from "@/lib/colors";
import type { SimSummary } from "@/lib/types";
import { fmt } from "@/lib/utils";
import { STATUS_LABEL, STATUS_TONE } from "./SimulationPage";

export function SimTable({ rows, selected, onSelect }: { rows: SimSummary[]; selected?: string[]; onSelect?: (id: string, checked: boolean) => void }) {
  const nav = useNavigate();
  return (
    <div className="overflow-x-auto">
      <table className="dt min-w-[640px]">
        <thead>
          <tr>{onSelect && <th>Select</th>}<th>Simulation</th><th>Status</th><th>Regions</th><th className="!text-right">Opinion</th><th className="!text-right">Virality</th><th className="!text-right">Updated</th></tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.id} onClick={() => nav(`/simulations/${s.id}`)} className="hoverable">
              {onSelect && <td onClick={(e) => e.stopPropagation()}><input type="checkbox" aria-label={`Select ${s.name}`} checked={selected?.includes(s.id) || false} disabled={["building_graph", "preparing", "queued", "running", "paused", "completed"].includes(s.status)} onChange={(e) => onSelect(s.id, e.target.checked)} /></td>}
              <td>
                <div className="font-medium text-fg">{s.name}</div>
                <div className="text-xs text-muted">
                  <span className="capitalize">{s.content_type}</span> · {s.platform}
                  {s.ab && <> · A/B{s.ab_winner ? ` (${s.ab_winner === "tie" ? "tie" : `${s.ab_winner} preferred`})` : ""}</>}
                  {s.dry && <> · dry run</>}
                </div>
              </td>
              <td>
                <Status tone={STATUS_TONE[s.status]}>{STATUS_LABEL[s.status]}</Status>
                {s.progress?.waiting_for_slot && <div className="text-xs text-muted">Waiting for an available run slot</div>}
                {s.status === "running" && s.progress?.rounds ? <Progress className="mt-1.5 w-24" value={s.progress.round / s.progress.rounds} /> : null}
              </td>
              <td className="text-muted">{s.regions.join(", ") || "All"}</td>
              <td className="r font-medium" style={{ color: s.score != null ? scoreColor(s.score) : undefined }}>{fmt.s2(s.score)}</td>
              <td className="r">{fmt.s1(s.viral)}</td>
              <td className="r whitespace-nowrap text-muted">{fmt.ago(s.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
