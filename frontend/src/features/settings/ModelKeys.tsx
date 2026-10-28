import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, KeyRound, RefreshCw, ShieldCheck, Trash2, XCircle } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/overlay";
import { Badge, Callout, Card, CardHeader, Field, Input, Skeleton } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { can, useAuth } from "@/lib/auth";
import { fmt } from "@/lib/utils";

interface ProviderInfo { id: string; label: string; needs_base_url: boolean; key_hint: string; docs: string }
interface SavedKey { provider: string; label: string; hint: string; base_url: string | null; status: "valid" | "invalid" | "unchecked"; status_message: string | null; last_checked_at: string | null; created_at: string; rotated_at: string | null }
interface Vault { keys: SavedKey[]; providers: ProviderInfo[]; active_provider: string | null }

const statusBadge = (s: SavedKey["status"]) =>
  s === "valid" ? <Badge tone="pos"><CheckCircle2 className="h-3 w-3" aria-hidden />Working</Badge>
    : s === "invalid" ? <Badge tone="neg"><XCircle className="h-3 w-3" aria-hidden />Rejected</Badge>
    : <Badge tone="warn">Not checked</Badge>;

export function ModelKeys() {
  const orgId = useAuth((s) => s.orgId);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: [orgId, "model-keys"], queryFn: () => api<Vault>("/model-keys") });
  const [editing, setEditing] = useState<ProviderInfo | null>(null);
  const [form, setForm] = useState({ api_key: "", base_url: "" });
  const refresh = () => { qc.invalidateQueries({ queryKey: [orgId, "model-keys"] }); qc.invalidateQueries({ queryKey: [orgId, "providers"] }); };
  const save = useMutation({
    mutationFn: () => api<SavedKey>(`/model-keys/${editing!.id}`, { method: "PUT", json: form }),
    onSuccess: (k) => { toast.success(`${k.label}: ${k.status_message}`); setEditing(null); refresh(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "The key could not be saved."),
  });
  const check = useMutation({
    mutationFn: (p: string) => api<SavedKey>(`/model-keys/${p}/check`, { method: "POST" }),
    onSuccess: (k) => { (k.status === "valid" ? toast.success : toast.error)(`${k.label}: ${k.status_message}`); refresh(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Check failed."),
  });
  const remove = useMutation({
    mutationFn: (p: string) => api(`/model-keys/${p}`, { method: "DELETE" }),
    onSuccess: () => { toast.success("Key removed"); refresh(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not remove the key."),
  });
  function open(p: ProviderInfo) { setForm({ api_key: "", base_url: q.data?.keys.find((k) => k.provider === p.id)?.base_url || "" }); setEditing(p); }
  function submit(e: FormEvent) { e.preventDefault(); save.mutate(); }

  if (q.isLoading) return <Card className="space-y-2 p-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-12" />)}</Card>;
  if (q.isError || !q.data) return <Callout tone="neg" title="Keys could not be loaded">Refresh the page to try again.</Callout>;
  const admin = can("admin");
  const saved = new Map(q.data.keys.map((k) => [k.provider, k]));

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
      <Card className="overflow-hidden">
        <CardHeader title="Model keys" divider subtitle="Your own keys for model providers. Each is checked with the provider before it is saved, stored encrypted, used only on the server for this workspace's runs, and never shown again in full." />
        <ul className="divide-y divide-line">
          {q.data.providers.map((p) => {
            const k = saved.get(p.id);
            return (
              <li key={p.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <KeyRound className="h-4 w-4 shrink-0 text-muted" aria-hidden />
                <div className="min-w-[180px] flex-1">
                  <div className="flex flex-wrap items-center gap-2 text-[13px] font-medium">{p.label}
                    {q.data.active_provider === p.id && <Badge tone="brand">In use</Badge>}
                    {k && statusBadge(k.status)}
                  </div>
                  <div className="text-xs text-muted">
                    {k ? <>Key <span className="mono">{k.hint}</span> · checked {fmt.ago(k.last_checked_at)}{k.rotated_at ? ` · replaced ${fmt.day(k.rotated_at)}` : ` · added ${fmt.day(k.created_at)}`}{k.status !== "valid" && k.status_message ? ` · ${k.status_message}` : ""}</>
                      : <>No key saved{p.docs && <> · <a className="text-brand hover:underline" href={p.docs} target="_blank" rel="noreferrer noopener">get a key</a></>}</>}
                  </div>
                </div>
                {admin && (
                  <div className="flex gap-1.5">
                    {k && <Button size="sm" variant="ghost" aria-label={`Check the ${p.label} key`} loading={check.isPending && check.variables === p.id} onClick={() => check.mutate(p.id)}><RefreshCw className="h-3.5 w-3.5" /></Button>}
                    <Button size="sm" onClick={() => open(p)}>{k ? "Replace" : "Add key"}</Button>
                    {k && <Button size="sm" variant="ghost" aria-label={`Remove the ${p.label} key`} onClick={() => window.confirm(`Remove the ${p.label} key? Runs that use ${p.label} will stop until a new key is added.`) && remove.mutate(p.id)}><Trash2 className="h-3.5 w-3.5" /></Button>}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </Card>
      <div className="space-y-4">
        <Callout tone="info" title="How your keys are protected">
          <ul className="mt-1 list-disc space-y-1 pl-4">
            <li>Encrypted at rest; only the server can read them.</li>
            <li>Shown back only as a masked hint, never in full, never written to logs.</li>
            <li>Used only for this workspace's runs. Other workspaces cannot see or use them.</li>
            <li>Spending limits apply to your own keys too.</li>
          </ul>
        </Callout>
        <Callout tone="info" title="Local models">Ollama, LM Studio, llama.cpp and vLLM need no key: choose them under Model provider (self-hosted Kruvim only).</Callout>
        {!admin && <Callout tone="info">Only workspace admins can add or change keys.</Callout>}
      </div>
      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)} title={editing ? `${saved.has(editing.id) ? "Replace" : "Add"} ${editing.label} key` : ""}
        footer={<><Button onClick={() => setEditing(null)}>Cancel</Button><Button variant="primary" type="submit" form="model-key-form" loading={save.isPending} disabled={!form.api_key.trim()}><ShieldCheck className="h-3.5 w-3.5" />Check and save</Button></>}>
        <form id="model-key-form" onSubmit={submit} className="space-y-3">
          {editing?.needs_base_url && <Field label="Base URL" hint="Usually ends in /v1"><Input type="url" required value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="https://…/v1" /></Field>}
          <Field label="API key" help="Kruvim makes one free, read-only call to the provider to confirm the key works. A key it rejects is not saved.">
            <Input type="password" autoComplete="off" spellCheck={false} required value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} placeholder={editing?.key_hint ? `${editing.key_hint}…` : ""} />
          </Field>
        </form>
      </Dialog>
    </div>
  );
}

interface Limits { monthly_calls: number | null; monthly_usd: number | null; member_daily_calls: number | null }
interface LimitsView { limits: Limits; used: { month_calls: number; month_usd: number; member_today_calls: number | null } }

export function UsageMeter({ label, used, limit, money }: { label: string; used: number; limit: number | null; money?: boolean }) {
  const show = (v: number) => (money ? `$${v.toFixed(2)}` : fmt.n(v));
  const pct = limit ? Math.min(100, (used / limit) * 100) : 0;
  return (
    <div>
      <div className="mb-1 flex justify-between text-[13px]"><span>{label}</span><span className="num text-muted">{show(used)}{limit ? ` of ${show(limit)}` : " · no limit"}</span></div>
      <div className="h-1.5 overflow-hidden rounded-full bg-raised" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
        <div className={pct >= 100 ? "h-full bg-neg" : pct >= 80 ? "h-full bg-warn" : "h-full bg-brand"} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function SpendingLimits() {
  const orgId = useAuth((s) => s.orgId);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: [orgId, "limits"], queryFn: () => api<LimitsView>("/limits") });
  const [f, setF] = useState({ monthly_calls: "", monthly_usd: "", member_daily_calls: "" });
  useEffect(() => {
    if (q.data) setF({ monthly_calls: q.data.limits.monthly_calls?.toString() ?? "", monthly_usd: q.data.limits.monthly_usd?.toString() ?? "",
      member_daily_calls: q.data.limits.member_daily_calls?.toString() ?? "" });
  }, [q.data]);
  const save = useMutation({
    mutationFn: () => api<LimitsView>("/limits", { method: "PUT", json: Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.trim() === "" ? null : Number(v)])) }),
    onSuccess: () => { toast.success("Spending limits saved"); qc.invalidateQueries({ queryKey: [orgId, "limits"] }); qc.invalidateQueries({ queryKey: [orgId, "usage"] }); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not save the limits."),
  });
  if (q.isLoading) return <Card className="p-5"><Skeleton className="h-40" /></Card>;
  if (q.isError || !q.data) return <Callout tone="neg" title="Limits could not be loaded">Refresh the page to try again.</Callout>;
  const admin = can("admin");
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
      <Card className="p-5">
        <CardHeader className="!p-0 pb-4" title="Spending limits" subtitle="Hard stops checked before every model call, on any key including your own. When a limit is reached the run stops cleanly, keeps its partial results and says why. Leave a field empty for no limit." />
        <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="grid gap-4 md:grid-cols-3">
          <Field label="Model calls per month" hint="Workspace"><Input type="number" min={1} inputMode="numeric" disabled={!admin} value={f.monthly_calls} onChange={set("monthly_calls")} placeholder="No limit" /></Field>
          <Field label="Dollars per month" hint="Workspace" help="Needs the model prices set under Model provider."><Input type="number" min={0.01} step="0.01" inputMode="decimal" disabled={!admin} value={f.monthly_usd} onChange={set("monthly_usd")} placeholder="No limit" /></Field>
          <Field label="Model calls per member per day"><Input type="number" min={1} inputMode="numeric" disabled={!admin} value={f.member_daily_calls} onChange={set("member_daily_calls")} placeholder="No limit" /></Field>
          {admin && <div className="md:col-span-3"><Button type="submit" variant="primary" loading={save.isPending}>Save limits</Button></div>}
        </form>
        {!admin && <Callout tone="info" className="mt-4">Only workspace admins can change limits.</Callout>}
      </Card>
      <Card className="space-y-4 p-5">
        <div className="section-title">Used so far</div>
        <UsageMeter label="Model calls this month" used={q.data.used.month_calls} limit={q.data.limits.monthly_calls} />
        <UsageMeter label="Spend this month" used={q.data.used.month_usd} limit={q.data.limits.monthly_usd} money />
        <UsageMeter label="Your model calls today" used={q.data.used.member_today_calls ?? 0} limit={q.data.limits.member_daily_calls} />
        <p className="text-xs text-muted">Months and days reset at midnight UTC. A run that would clearly not fit is refused before it starts.</p>
      </Card>
    </div>
  );
}
