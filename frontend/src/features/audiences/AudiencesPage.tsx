import { useQuery } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Page } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Card, Empty, Segmented, Skeleton, Switch } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt } from "@/lib/utils";

export function describeAudience(f: any): string {
  const parts: string[] = [];
  if (f.regions?.length) parts.push(f.regions.join(", "));
  if (f.age_min || f.age_max) parts.push(`ages ${f.age_min || 16}–${f.age_max || 70}`);
  if (f.genders?.length === 1) parts.push(f.genders[0] === "female" ? "women" : "men");
  if (f.citizens_only) parts.push("citizens");
  if (f.expats_only) parts.push("expatriates");
  if (f.platforms?.length) parts.push(`uses ${f.platforms.join("/")}`);
  if (f.interests?.length) parts.push(`into ${f.interests.map((x: string) => x.replace("_", " ")).join(", ")}`);
  if (f.professions?.length) parts.push(f.professions.join(", "));
  if (f.incomes?.length) parts.push(`${f.incomes.join("/")} income`);
  for (const [k, v] of Object.entries(f.ocean || {}) as [string, number[]][]) parts.push(`${k} ${v[0]}–${v[1]}`);
  return parts.join(" · ") || "Everyone";
}

export default function AudiencesPage() {
  const orgId = useAuth((s) => s.orgId);
  const [scope, setScope] = useState<"all" | "mine" | "community">("all");
  const q = useQuery({ queryKey: [orgId, "templates", scope], queryFn: () => api<any[]>(`/audience-templates?scope=${scope}`) });
  async function share(t: any, shared: boolean) {
    try { await api(`/audience-templates/${t.id}`, { method: "PATCH", json: { ...t, shared } }); q.refetch(); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not update"); }
  }
  async function remove(t: any) {
    if (!confirm(`Delete "${t.name}"?`)) return;
    await api(`/audience-templates/${t.id}`, { method: "DELETE" });
    q.refetch();
  }
  return (
    <Page title="Saved audiences" subtitle="Saved audience definitions you can load into any simulation. Share one and it appears in every workspace's community library; accuracy comes from calibration against real results."
      actions={<Segmented size="md" value={scope} onChange={setScope} options={[{ value: "all", label: "All" }, { value: "mine", label: "This workspace" }, { value: "community", label: "Community" }]} />}>
      <Card className="overflow-hidden">
        {q.isLoading ? <div className="space-y-2 p-4"><Skeleton /><Skeleton /></div>
          : (q.data || []).length === 0 ? <Empty title="No saved audiences">Build an audience in a new simulation and choose “Save this audience”.</Empty> : (
            <div className="overflow-x-auto">
              <table className="dt min-w-[820px]">
                <thead><tr><th>Audience</th><th>Filters</th><th>Source</th><th className="!text-right">Uses</th><th className="!text-right">Accuracy</th><th>Shared</th><th className="w-10" /></tr></thead>
                <tbody>{q.data!.map((t) => (
                  <tr key={t.id}>
                    <td><div className="font-medium">{t.name}</div><div className="text-xs text-muted">{t.mine ? "This workspace" : "Community"} · {fmt.day(t.created_at)}</div>
                      {t.description && <div className="mt-0.5 max-w-xs text-xs text-muted">{t.description}</div>}</td>
                    <td className="max-w-sm text-xs text-muted">{describeAudience(t.filters)}</td>
                    <td className="max-w-[200px] text-xs text-muted">{t.source_citation || "–"}</td>
                    <td className="r">{fmt.n(t.uses)}</td>
                    <td className="r">{t.accuracy != null ? fmt.pct(t.accuracy) : <span className="text-muted">Not yet calibrated</span>}</td>
                    <td>{t.mine ? <Switch checked={t.shared} onChange={(v) => share(t, v)} /> : <span className="text-xs text-muted">Shared</span>}</td>
                    <td>{t.mine && <Button size="icon-sm" variant="ghost" aria-label={`Delete ${t.name}`} onClick={() => remove(t)}><Trash2 className="h-3.5 w-3.5" /></Button>}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
      </Card>
    </Page>
  );
}
