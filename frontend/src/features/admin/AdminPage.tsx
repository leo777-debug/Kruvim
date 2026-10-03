import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Navigate } from "react-router-dom";
import { toast } from "sonner";
import { Page } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/overlay";
import { Card, CardHeader, Input, KV, Stat, UnderlineTabs } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt } from "@/lib/utils";
import { ProviderForm } from "../settings/ProviderForm";

export default function AdminPage() {
  const user = useAuth((s) => s.user);
  const [tab, setTab] = useState("overview");
  const ov = useQuery({ queryKey: ["admin-overview"], queryFn: () => api("/admin/overview"), enabled: !!user?.is_superuser, refetchInterval: 10000 });
  const orgs = useQuery({ queryKey: ["admin-orgs"], queryFn: () => api<any[]>("/admin/orgs"), enabled: !!user?.is_superuser });
  const prov = useQuery({ queryKey: ["admin-provider"], queryFn: () => api("/admin/provider"), enabled: !!user?.is_superuser });
  const [delta, setDelta] = useState<Record<string, string>>({});
  const upd = useMutation({ mutationFn: ({ id, body }: any) => api(`/admin/orgs/${id}`, { method: "PATCH", json: body }), onSuccess: () => { orgs.refetch(); toast.success("Updated"); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed") });
  if (!user?.is_superuser) return <Navigate to="/" />;
  const o = ov.data;
  return (
    <Page title="Platform admin" subtitle="Tenants, plans, credits, the shared model key and system health.">
      <UnderlineTabs value={tab} onChange={setTab} className="mb-5" tabs={[{ key: "overview", label: "Overview" }, { key: "orgs", label: "Organisations" }, { key: "provider", label: "Platform model key" }]} />
      {tab === "overview" && o && (
        <div className="space-y-5">
          <Card className="grid grid-cols-2 divide-line md:grid-cols-4 md:divide-x">
            <Stat className="p-4" label="Organisations" value={fmt.n(o.orgs)} />
            <Stat className="p-4" label="Users" value={fmt.n(o.users)} />
            <Stat className="p-4" label="Job queue" value={o.queue.mode === "redis" ? fmt.n(o.queue.queued) : fmt.n(o.queue.running)} sub={o.queue.mode === "redis" ? "Jobs waiting (Redis / arq)" : "In-process jobs running"} />
            <Stat className="p-4" label="Active simulations" value={fmt.n((o.simulations.running || 0) + (o.simulations.queued || 0))} />
          </Card>
          <Card className="max-w-md p-4"><div className="section-title mb-1">Simulations by status</div>
            <KV rows={Object.entries(o.simulations).map(([k, v]: any) => [<span className="capitalize">{k.replace("_", " ")}</span>, fmt.n(v)])} /></Card>
        </div>
      )}
      {tab === "orgs" && (
        <Card className="overflow-x-auto">
          <table className="dt min-w-[760px]">
            <thead><tr><th>Organisation</th><th>Plan</th><th className="!text-right">Credits</th><th className="!text-right">Simulations</th><th>Adjust credits</th></tr></thead>
            <tbody>{(orgs.data || []).map((g) => (
              <tr key={g.id}>
                <td><div className="font-medium">{g.name}</div><div className="text-xs text-muted">Created {fmt.day(g.created_at)}</div></td>
                <td className="w-40"><Select value={g.plan} onChange={(v) => upd.mutate({ id: g.id, body: { plan: v } })} options={["free", "pro", "business", "enterprise"].map((p) => ({ value: p, label: p[0].toUpperCase() + p.slice(1) }))} /></td>
                <td className="r">{fmt.n(g.credits_balance)}</td><td className="r">{fmt.n(g.simulations)}</td>
                <td><div className="flex gap-1.5"><Input className="w-28" placeholder="+5000" value={delta[g.id] || ""} onChange={(e) => setDelta({ ...delta, [g.id]: e.target.value })} />
                  <Button size="sm" disabled={!Number(delta[g.id])} onClick={() => { upd.mutate({ id: g.id, body: { credits_delta: Number(delta[g.id]) } }); setDelta({ ...delta, [g.id]: "" }); }}>Apply</Button></div></td>
              </tr>
            ))}</tbody>
          </table>
        </Card>
      )}
      {tab === "provider" && prov.data && (
        <Card>
          <CardHeader title="Platform model key" subtitle="Used by every workspace that has not connected its own provider. Usage is metered against their credits." />
          <div className="px-5 pb-5"><ProviderForm presets={prov.data.presets} current={prov.data.config} endpoint={{ save: "/admin/provider", test: "/providers/test", models: "/providers/models" }} onSaved={() => prov.refetch()} /></div>
        </Card>
      )}
    </Page>
  );
}
