import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/overlay";
import { Badge, Callout, Card, CardHeader, Field, Input, Stat } from "@/components/ui/primitives";
import { QueryGate } from "@/components/ui/states";
import { api, ApiError } from "@/lib/api";
import { fmt } from "@/lib/utils";

const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong.");
const bytes = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${fmt.k(n)}B`);
const Empty = ({ children }: { children: string }) => <p className="px-4 py-6 text-[13px] text-muted">{children}</p>;

export function BetaInvites() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin-invites"], queryFn: () => api("/admin/beta-invites") });
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ email: "", note: "", max_uses: "1", days: "30" });
  const [made, setMade] = useState<{ code: string; signup_url: string } | null>(null);
  const create = useMutation({
    mutationFn: () => api("/admin/beta-invites", { json: { email: f.email || null, note: f.note, max_uses: Number(f.max_uses), days: Number(f.days) } }),
    onSuccess: (r) => { setMade(r); qc.invalidateQueries({ queryKey: ["admin-invites"] }); }, onError: fail,
  });
  const revoke = useMutation({ mutationFn: (id: string) => api(`/admin/beta-invites/${id}`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-invites"] }), onError: fail });
  const copy = (t: string) => { navigator.clipboard.writeText(t); toast.success("Copied"); };
  return (
    <QueryGate query={q} what="invites">{(d: any) => (
      <div className="space-y-4">
        <Callout tone="info" title={d.registration_open ? "Sign-up is open to everyone" : "Sign-up is invite-only"}>
          {d.registration_open ? "Anyone can create an account. Set KRUVIM_ALLOW_REGISTRATION=false for an invite-only beta." :
            <>New people need an invite code{d.allowlist.length ? <>, or an address on the allowlist ({d.allowlist.join(", ")})</> : null}. Workspace admins can still invite teammates into their own workspace.</>}
        </Callout>
        <Card className="overflow-hidden">
          <CardHeader title="Beta invite codes" divider actions={<Button size="sm" variant="primary" onClick={() => { setMade(null); setOpen(true); }}>Create code</Button>} />
          {!d.invites.length ? <Empty>No invite codes yet.</Empty> : (
            <div className="overflow-x-auto" tabIndex={0} data-scroll-region><table className="dt min-w-[640px]">
              <thead><tr><th>For</th><th>Uses</th><th>Expires</th><th>State</th><th /></tr></thead>
              <tbody>{d.invites.map((i: any) => (
                <tr key={i.id}><td><div className="font-medium">{i.email || "Anyone with the code"}</div><div className="text-2xs text-muted">{i.note}</div></td>
                  <td>{i.uses} / {i.max_uses}</td><td>{fmt.day(i.expires_at)}</td>
                  <td><Badge tone={i.state === "active" ? "pos" : "default"}>{i.state}</Badge></td>
                  <td className="!text-right">{i.state === "active" && <Button size="sm" variant="danger" onClick={() => revoke.mutate(i.id)}>Revoke</Button>}</td></tr>
              ))}</tbody>
            </table></div>)}
        </Card>
        <Dialog open={open} onOpenChange={setOpen} title="New invite code" footer={made ? <Button onClick={() => setOpen(false)}>Done</Button> :
          <><Button onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" type="submit" form="invite-form" loading={create.isPending}>Create</Button></>}>
          {made ? <div className="space-y-3"><Callout tone="warn">Copy this now. Only its fingerprint is stored, so it can't be shown again.</Callout>
            <Field label="Code"><div className="flex gap-2"><Input readOnly value={made.code} className="mono" /><Button aria-label="Copy the code" onClick={() => copy(made.code)}><Copy className="h-3.5 w-3.5" /></Button></div></Field>
            <Field label="Sign-up link"><div className="flex gap-2"><Input readOnly value={made.signup_url} className="mono" /><Button aria-label="Copy the sign-up link" onClick={() => copy(made.signup_url)}><Copy className="h-3.5 w-3.5" /></Button></div></Field></div>
            : <form id="invite-form" className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
              <Field label="Email" hint="Optional: only this address can use it"><Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
              <Field label="Note" hint="Optional"><Input maxLength={300} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} placeholder="Creator cohort 1" /></Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="How many sign-ups"><Input type="number" min={1} max={500} value={f.max_uses} onChange={(e) => setF({ ...f, max_uses: e.target.value })} /></Field>
                <Field label="Valid for (days)"><Input type="number" min={1} max={365} value={f.days} onChange={(e) => setF({ ...f, days: e.target.value })} /></Field>
              </div>
            </form>}
        </Dialog>
      </div>
    )}</QueryGate>
  );
}

export function Users() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const q = useQuery({ queryKey: ["admin-users", search], queryFn: () => api<any[]>(`/admin/users?q=${encodeURIComponent(search)}`) });
  const toggle = useMutation({ mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) => api(`/admin/users/${id}`, { method: "PATCH", json: { is_active } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }), onError: fail });
  return (
    <Card className="overflow-hidden">
      <CardHeader title="Users" divider actions={<Input aria-label="Search users" className="w-56" placeholder="Search name or email" value={search} onChange={(e) => setSearch(e.target.value)} />} />
      <QueryGate query={q} what="users">{(rows) => !rows.length ? <Empty>No users match.</Empty> : (
        <div className="overflow-x-auto" tabIndex={0} data-scroll-region><table className="dt min-w-[720px]">
          <thead><tr><th>User</th><th>Workspaces</th><th>Joined</th><th>Last sign-in</th><th /></tr></thead>
          <tbody>{rows.map((u) => (
            <tr key={u.id}><td><div className="font-medium">{u.name}{u.is_superuser && <Badge tone="brand" className="ml-2">admin</Badge>}{!u.is_active && <Badge tone="neg" className="ml-2">disabled</Badge>}</div><div className="text-2xs text-muted">{u.email}</div></td>
              <td className="max-w-[220px] truncate text-muted">{u.workspaces.join(", ")}</td><td>{fmt.day(u.created_at)}</td><td>{fmt.ago(u.last_login_at)}</td>
              <td className="!text-right">{!u.is_superuser && <Button size="sm" variant={u.is_active ? "danger" : "secondary"}
                onClick={() => (!u.is_active || window.confirm(`Disable ${u.email}? They are signed out everywhere and can't sign in.`)) && toggle.mutate({ id: u.id, is_active: !u.is_active })}>
                {u.is_active ? "Disable" : "Enable"}</Button>}</td></tr>
          ))}</tbody>
        </table></div>)}</QueryGate>
    </Card>
  );
}

export function UsageView() {
  const q = useQuery({ queryKey: ["admin-usage"], queryFn: () => api("/admin/usage") });
  return (
    <QueryGate query={q} what="usage">{(d: any) => (
      <div className="space-y-4">
        <Card className="grid grid-cols-2 divide-line md:grid-cols-3 md:divide-x">
          <Stat className="p-4" label="Shared key calls today" value={fmt.n(d.shared_key_today.platform)} sub={d.shared_key_today.platform_limit ? `of ${fmt.n(d.shared_key_today.platform_limit)} daily limit` : "no daily limit"} />
          <Stat className="p-4" label={`Model calls since ${fmt.day(d.month)}`} value={fmt.n(d.orgs.reduce((a: number, o: any) => a + o.calls, 0))} />
          <Stat className="p-4" label="Known model cost this month" value={`$${d.orgs.reduce((a: number, o: any) => a + (o.cost_usd || 0), 0).toFixed(2)}`} sub="Only where prices are set" />
        </Card>
        <Card className="overflow-hidden"><CardHeader title="By workspace, this month" divider />
          <div className="overflow-x-auto" tabIndex={0} data-scroll-region><table className="dt min-w-[640px]">
            <thead><tr><th>Workspace</th><th>Plan</th><th className="!text-right">Calls</th><th className="!text-right">Tokens in / out</th><th className="!text-right">Cost</th><th className="!text-right">Credits left</th></tr></thead>
            <tbody>{d.orgs.map((o: any) => (<tr key={o.id}><td className="font-medium">{o.name}</td><td className="capitalize">{o.plan}</td><td className="r">{fmt.n(o.calls)}</td>
              <td className="r">{fmt.k(o.input_tokens)} / {fmt.k(o.output_tokens)}</td><td className="r">{o.cost_usd != null ? `$${o.cost_usd.toFixed(2)}` : "–"}</td><td className="r">{fmt.n(o.credits_balance)}</td></tr>))}</tbody>
          </table></div></Card>
      </div>
    )}</QueryGate>
  );
}

export function FailedJobs() {
  const q = useQuery({ queryKey: ["admin-failed"], queryFn: () => api<any[]>("/admin/failed-jobs"), refetchInterval: 30_000 });
  return (
    <Card className="overflow-hidden"><CardHeader title="Failed jobs, last 14 days" subtitle="Simulations or reports that stopped with an error. Unexpected crashes also appear under Errors with their details." divider />
      <QueryGate query={q} what="failed jobs">{(rows) => !rows.length ? <Empty>No failed jobs. 🎉</Empty> : (
        <div className="overflow-x-auto" tabIndex={0} data-scroll-region><table className="dt min-w-[720px]">
          <thead><tr><th>Test</th><th>Workspace</th><th>What failed</th><th>When</th></tr></thead>
          <tbody>{rows.map((r) => (<tr key={r.id}><td className="font-medium">{r.name}<div className="mono text-2xs text-muted">{r.id}</div></td><td>{r.workspace}</td>
            <td className="max-w-[360px]"><div>{r.status === "failed" ? "Simulation" : "Report"}</div><div className="text-2xs text-muted">{r.error || "No message recorded"}</div></td><td>{fmt.ago(r.updated_at)}</td></tr>))}</tbody>
        </table></div>)}</QueryGate>
    </Card>
  );
}

export function DataView() {
  const q = useQuery({ queryKey: ["admin-data"], queryFn: () => api("/admin/data") });
  return (
    <QueryGate query={q} what="uploaded data">{(d: any) => (
      <div className="space-y-4">
        <Card className="grid grid-cols-2 divide-line md:grid-cols-4 md:divide-x">
          <Stat className="p-4" label="Barometer documents" value={fmt.n(d.barometers.ready)} sub={`${bytes(d.barometers.bytes)} · ${d.barometers.quarantined} quarantined`} />
          <Stat className="p-4" label="Uploaded content files" value={fmt.n(d.assets.count)} sub={bytes(d.assets.bytes)} />
          <Stat className="p-4" label="Calibration datasets" value={fmt.n(d.datasets)} />
          <Stat className="p-4" label="Library" value={<Link className="text-brand text-base" to="/barometers">Open</Link>} />
        </Card>
        <Card className="overflow-hidden"><CardHeader title="Recently quarantined files" subtitle="Received but unreadable; never shown to agents." divider />
          {!d.recent_quarantined.length ? <Empty>Nothing quarantined.</Empty> : (
            <div className="overflow-x-auto" tabIndex={0} data-scroll-region><table className="dt min-w-[640px]">
              <thead><tr><th>File</th><th>Workspace</th><th>Reason</th><th>When</th></tr></thead>
              <tbody>{d.recent_quarantined.map((x: any) => (<tr key={x.id}><td className="font-medium">{x.title}<div className="text-2xs text-muted">{x.filename}</div></td><td>{x.workspace}</td>
                <td className="max-w-[360px] text-muted">{x.reason}</td><td>{fmt.ago(x.created_at)}</td></tr>))}</tbody>
            </table></div>)}
        </Card>
      </div>
    )}</QueryGate>
  );
}

export function Errors() {
  const [source, setSource] = useState("");
  const q = useQuery({ queryKey: ["admin-errors", source], queryFn: () => api(`/admin/errors?source=${source}`), refetchInterval: 30_000 });
  return (
    <QueryGate query={q} what="errors">{(d: any) => (
      <div className="space-y-4">
        <Card className="grid grid-cols-3 divide-x divide-line">
          {(["server", "job", "client"] as const).map((k) => <Stat key={k} className="p-4" label={{ server: "Server errors", job: "Job crashes", client: "Browser errors" }[k]} value={fmt.n(d.last_24h[k] || 0)} sub="last 24 hours" />)}
        </Card>
        <Card className="overflow-hidden">
          <CardHeader title="Recent errors" subtitle="Kept 30 days. Keys and tokens are removed before anything is stored." divider actions={
            <div className="flex gap-1" role="group" aria-label="Filter errors">{[["", "All"], ["server", "Server"], ["job", "Jobs"], ["client", "Browser"]].map(([k, l]) =>
              <Button key={k} size="sm" variant={source === k ? "primary" : "ghost"} aria-pressed={source === k} onClick={() => setSource(k)}>{l}</Button>)}</div>} />
          {!d.events.length ? <Empty>No errors recorded.</Empty> : (
            <ul className="divide-y divide-line">{d.events.map((e: any) => (
              <li key={e.id} className="p-3 text-[13px]"><details><summary className="cursor-pointer"><Badge className="mr-2">{e.source}</Badge><span className="font-medium">{e.message}</span>
                <span className="ml-2 text-2xs text-muted">{e.path} · {fmt.ago(e.created_at)}{e.request_id ? ` · ref ${e.request_id}` : ""}</span></summary>
                {e.detail && <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-raised p-2 font-mono text-[11px]" tabIndex={0} data-scroll-region>{e.detail}</pre>}</details></li>
            ))}</ul>)}
        </Card>
      </div>
    )}</QueryGate>
  );
}
