import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Page } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Dialog, Select } from "@/components/ui/overlay";
import { Callout, Card, CardHeader, Field, Input, KV, Status, UnderlineTabs } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { can, useAuth } from "@/lib/auth";
import { fmt } from "@/lib/utils";
import { ProviderForm } from "./ProviderForm";

export default function SettingsPage() {
  const [sp, setSp] = useSearchParams();
  const tab = sp.get("tab") || "provider";
  return (
    <Page title="Settings" subtitle="Workspace, team, access and the model that powers your agents.">
      <UnderlineTabs value={tab} onChange={(t) => setSp({ tab: t })} className="mb-5" tabs={[
        { key: "provider", label: "Model provider" }, { key: "org", label: "Workspace" }, { key: "members", label: "Members" },
        { key: "keys", label: "API keys" }, { key: "audit", label: "Audit log" }, { key: "branding", label: "Branding" }, { key: "profile", label: "Profile" },
      ]} />
      {tab === "provider" && <Provider />}
      {tab === "org" && <Org openNew={!!sp.get("new")} />}
      {tab === "members" && <Members />}
      {tab === "keys" && <Keys />}
      {tab === "audit" && <Audit />}
      {tab === "branding" && <Branding />}
      {tab === "profile" && <Profile />}
    </Page>
  );
}

function Provider() {
  const orgId = useAuth((s) => s.orgId);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: [orgId, "providers"], queryFn: () => api("/providers") });
  if (!q.data) return null;
  const a = q.data.active;
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
      <Card className="p-5">
        {!can("admin") && <Callout tone="info" className="mb-4">Only workspace admins can change the model provider.</Callout>}
        <ProviderForm presets={q.data.presets} current={q.data.configs[0] || null} canClear
          endpoint={{ save: "/providers", test: "/providers/test", models: "/providers/models", clear: "/providers" }}
          onSaved={() => { qc.invalidateQueries({ queryKey: [orgId, "providers"] }); qc.invalidateQueries({ queryKey: [orgId, "usage"] }); }} />
      </Card>
      <div className="space-y-4">
        <Card className="p-4">
          <div className="section-title mb-1">Currently in use</div>
          <KV rows={[["Provider", q.data.presets[a.preset]?.label || a.preset],
            ["Source", a.source === "org" ? "Workspace key" : a.source === "platform" ? "Kruvim platform key" : a.source === "env" ? "Server environment" : "None (dry run)"],
            ["Voice model", a.voice_model || "–"], ["Analyst model", a.report_model || "–"], ["Metering", a.metered ? "Credits charged" : "Not metered"]]} />
        </Card>
        <Callout tone="info" title="Your own key or a local model">Your key is used only for your workspace's jobs and never shown again after saving.
          Local servers (Ollama, LM Studio, llama.cpp, vLLM) keep content on your hardware.</Callout>
      </div>
    </div>
  );
}

function Org({ openNew }: { openNew: boolean }) {
  const orgId = useAuth((s) => s.orgId);
  const { setOrgs, switchOrg } = useAuth();
  const nav = useNavigate();
  const q = useQuery({ queryKey: [orgId, "org"], queryFn: () => api("/orgs/current") });
  const [name, setName] = useState("");
  const [newOpen, setNewOpen] = useState(openNew);
  const [newName, setNewName] = useState("");
  useEffect(() => { if (q.data) setName(q.data.name); }, [q.data]);
  const save = useMutation({ mutationFn: () => api("/orgs/current", { method: "PATCH", json: { name } }), onSuccess: async () => {
    const me = await api("/auth/me"); setOrgs(me.orgs, me.user); toast.success("Saved"); } });
  const create = useMutation({ mutationFn: () => api("/orgs", { json: { name: newName } }), onSuccess: async (o) => {
    const me = await api("/auth/me"); setOrgs(me.orgs, me.user); switchOrg(o.id); setNewOpen(false); nav("/"); toast.success("Workspace created"); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed") });
  return (
    <Card className="max-w-2xl p-5">
      <div className="grid grid-cols-[1fr_auto] items-end gap-3">
        <Field label="Workspace name"><Input value={name} onChange={(e) => setName(e.target.value)} disabled={!can("admin")} /></Field>
        <Button onClick={() => save.mutate()} disabled={!can("admin")} loading={save.isPending}>Save</Button>
      </div>
      {q.data && <KV className="mt-5" rows={[["Plan", <span className="capitalize">{q.data.plan}</span>], ["Members", q.data.members],
        ["Concurrent runs", q.data.plan_limits.max_concurrent], ["Created", fmt.day(q.data.created_at)]]} />}
      <div className="mt-6 border-t border-line pt-4"><Button onClick={() => setNewOpen(true)}>Create another workspace</Button></div>
      <Dialog open={newOpen} onOpenChange={setNewOpen} title="New workspace" footer={<><Button onClick={() => setNewOpen(false)}>Cancel</Button>
        <Button variant="primary" disabled={!newName.trim()} loading={create.isPending} onClick={() => create.mutate()}>Create</Button></>}>
        <Field label="Name"><Input autoFocus value={newName} onChange={(e) => setNewName(e.target.value)} /></Field>
      </Dialog>
    </Card>
  );
}

function Members() {
  const orgId = useAuth((s) => s.orgId);
  const q = useQuery({ queryKey: [orgId, "members"], queryFn: () => api("/members") });
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ email: "", role: "member" });
  const [link, setLink] = useState<string | null>(null);
  const invite = useMutation({ mutationFn: () => api("/members/invites", { json: f }), onSuccess: (r) => { setLink(r.accept_url); q.refetch(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed") });
  const role = useMutation({ mutationFn: ({ id, role }: any) => api(`/members/${id}`, { method: "PATCH", json: { role } }), onSuccess: () => q.refetch(),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed") });
  const remove = useMutation({ mutationFn: (id: string) => api(`/members/${id}`, { method: "DELETE" }), onSuccess: () => q.refetch(),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed") });
  return (
    <Card className="overflow-hidden">
      <CardHeader title="Members" subtitle="Owners and admins manage billing, keys and members. Members run simulations. Viewers read results." divider
        actions={can("admin") && <Button size="sm" variant="primary" onClick={() => { setOpen(true); setLink(null); }}>Invite member</Button>} />
      <div className="overflow-x-auto"><table className="dt min-w-[680px]">
        <thead><tr><th>Name</th><th>Status</th><th className="w-40">Role</th><th className="w-12" /></tr></thead>
        <tbody>
        {(q.data?.members || []).map((m: any) => (
          <tr key={m.id}>
            <td><div className="font-medium">{m.name}</div><div className="text-xs text-muted">{m.email}</div></td>
            <td className="text-xs text-muted">Joined {fmt.day(m.joined_at)} · last active {fmt.ago(m.last_login_at)}</td>
            <td>{can("admin") ? <Select value={m.role} onChange={(v) => role.mutate({ id: m.id, role: v })} options={["owner", "admin", "member", "viewer"].map((r) => ({ value: r, label: r[0].toUpperCase() + r.slice(1) }))} /> : <span className="capitalize">{m.role}</span>}</td>
            <td>{can("admin") && m.role !== "owner" && <Button size="icon-sm" variant="ghost" aria-label={`Remove ${m.email}`} onClick={() => confirm(`Remove ${m.email}?`) && remove.mutate(m.id)}><Trash2 className="h-3.5 w-3.5" /></Button>}</td>
          </tr>
        ))}
        {(q.data?.invites || []).map((i: any) => (
          <tr key={i.id}><td className="text-muted">{i.email}</td><td><Status tone="warn">Invited · expires {fmt.day(i.expires_at)}</Status></td><td className="capitalize text-muted">{i.role}</td>
            <td>{can("admin") && <Button size="icon-sm" variant="ghost" aria-label="Cancel invite" onClick={async () => { await api(`/members/invites/${i.id}`, { method: "DELETE" }); q.refetch(); }}><Trash2 className="h-3.5 w-3.5" /></Button>}</td></tr>
        ))}
      </tbody></table></div>
      <Dialog open={open} onOpenChange={setOpen} title="Invite a teammate" description="Email delivery depends on your deployment; share the link below with the invitee."
        footer={link ? <Button onClick={() => setOpen(false)}>Done</Button> : <><Button onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" loading={invite.isPending} onClick={() => invite.mutate()}>Create invite</Button></>}>
        {link ? (
          <div className="space-y-2"><div className="text-xs text-muted">Invite link (valid 7 days):</div>
            <div className="flex gap-2"><Input readOnly value={link} /><Button onClick={() => { navigator.clipboard.writeText(link); toast.success("Copied"); }}><Copy className="h-3.5 w-3.5" /></Button></div></div>
        ) : (
          <div className="grid grid-cols-[1fr_140px] gap-3">
            <Field label="Email"><Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
            <Field label="Role"><Select value={f.role} onChange={(v) => setF({ ...f, role: v })} options={["admin", "member", "viewer"].map((r) => ({ value: r, label: r }))} /></Field>
          </div>
        )}
      </Dialog>
    </Card>
  );
}

function Keys() {
  const orgId = useAuth((s) => s.orgId);
  const q = useQuery({ queryKey: [orgId, "keys"], queryFn: () => api<any[]>("/api-keys"), enabled: can("admin") });
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", role: "member" });
  const [raw, setRaw] = useState<string | null>(null);
  const create = useMutation({ mutationFn: () => api("/api-keys", { json: f }), onSuccess: (r) => { setRaw(r.key); q.refetch(); } });
  if (!can("admin")) return <Callout tone="info">Only admins can manage API keys.</Callout>;
  return (
    <Card className="overflow-hidden">
      <CardHeader title="API keys" divider subtitle={<>Programmatic access to everything in the UI: <code className="mono">Authorization: Bearer krv_…</code> against <code className="mono">/api/v1</code>. Reference at <a className="text-brand hover:underline" href="/api/docs" target="_blank" rel="noreferrer">/api/docs</a>.</>}
        actions={<Button size="sm" variant="primary" onClick={() => { setOpen(true); setRaw(null); }}>Create key</Button>} />
      {(q.data || []).length === 0 ? <div className="px-4 py-6 text-[13px] text-muted">No API keys yet.</div> : (
      <div className="overflow-x-auto"><table className="dt min-w-[680px]">
        <thead><tr><th>Name</th><th>Key</th><th>Role</th><th>Activity</th><th className="w-28" /></tr></thead>
        <tbody>
        {(q.data || []).map((k) => (
          <tr key={k.id}>
            <td className="font-medium">{k.name}</td><td className="mono text-muted">{k.prefix}…</td><td className="capitalize">{k.role}</td>
            <td className="text-xs text-muted">Created {fmt.day(k.created_at)} · last used {fmt.ago(k.last_used_at)}</td>
            <td className="text-right">{k.revoked ? <Status tone="neg">Revoked</Status> : <Button size="sm" variant="danger" onClick={async () => { await api(`/api-keys/${k.id}`, { method: "DELETE" }); q.refetch(); }}>Revoke</Button>}</td>
          </tr>
        ))}
      </tbody></table></div>)}
      <Dialog open={open} onOpenChange={setOpen} title="New API key" footer={raw ? <Button onClick={() => setOpen(false)}>Done</Button> : <><Button onClick={() => setOpen(false)}>Cancel</Button>
        <Button variant="primary" disabled={!f.name} loading={create.isPending} onClick={() => create.mutate()}>Create</Button></>}>
        {raw ? <div className="space-y-2"><Callout tone="warn">Copy this key now. It will not be shown again.</Callout>
          <div className="flex gap-2"><Input readOnly value={raw} className="mono" /><Button onClick={() => { navigator.clipboard.writeText(raw); toast.success("Copied"); }}><Copy className="h-3.5 w-3.5" /></Button></div></div>
          : <div className="grid grid-cols-[1fr_140px] gap-3"><Field label="Name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="CI pipeline" /></Field>
            <Field label="Role"><Select value={f.role} onChange={(v) => setF({ ...f, role: v })} options={["admin", "member", "viewer"].map((r) => ({ value: r, label: r }))} /></Field></div>}
      </Dialog>
    </Card>
  );
}

function Audit() {
  const orgId = useAuth((s) => s.orgId);
  const q = useQuery({ queryKey: [orgId, "audit"], queryFn: () => api<any[]>("/audit?limit=300"), enabled: can("admin") });
  if (!can("admin")) return <Callout tone="info">Only admins can view the audit log.</Callout>;
  return (
    <Card className="max-h-[70vh] overflow-auto">
      <table className="dt min-w-[760px]">
        <thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Target</th><th>IP address</th></tr></thead>
        <tbody>{(q.data || []).map((a, i) => (
          <tr key={i}><td className="num whitespace-nowrap text-muted">{fmt.date(a.at)}</td><td>{a.user || "API key"}</td>
            <td className="mono whitespace-nowrap">{a.action}</td><td className="max-w-[320px] truncate text-muted">{a.target}</td><td className="mono text-muted">{a.ip}</td></tr>
        ))}</tbody>
      </table>
    </Card>
  );
}

function Profile() {
  const user = useAuth((s) => s.user);
  const [f, setF] = useState({ current_password: "", new_password: "" });
  const m = useMutation({ mutationFn: () => api("/auth/password", { json: f }), onSuccess: () => { toast.success("Password changed. Other sessions were signed out."); setF({ current_password: "", new_password: "" }); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed") });
  return (
    <Card className="max-w-xl space-y-4 p-5">
      <div><div className="section-title">{user?.name}</div><div className="text-[13px] text-muted">{user?.email}{user?.is_superuser && " · platform administrator"}</div></div>
      <Field label="Current password"><Input type="password" value={f.current_password} onChange={(e) => setF({ ...f, current_password: e.target.value })} /></Field>
      <Field label="New password" hint="At least 10 characters"><Input type="password" value={f.new_password} onChange={(e) => setF({ ...f, new_password: e.target.value })} /></Field>
      <Button variant="primary" disabled={f.new_password.length < 10} loading={m.isPending} onClick={() => m.mutate()}>Change password</Button>
    </Card>
  );
}


function Branding() {
  const orgId = useAuth((s) => s.orgId);
  const orgs = useAuth((s) => s.orgs);
  const plan = orgs.find((o) => o.id === orgId)?.plan;
  const qc = useQueryClient();
  const q = useQuery({ queryKey: [orgId, "branding"], queryFn: () => api("/orgs/current/branding") });
  const [f, setF] = useState({ product_name: "", accent: "", logo_url: "", report_footer: "" });
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (q.data) setF({ product_name: "", accent: "", logo_url: "", report_footer: "", ...q.data }); }, [q.data]);
  const allowed = plan === "business" || plan === "enterprise" || useAuth.getState().user?.is_superuser;
  async function save() {
    setBusy(true);
    try {
      await api("/orgs/current/branding", { method: "PUT", json: f });
      qc.invalidateQueries({ queryKey: [orgId, "branding"] });
      toast.success("Branding saved");
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not save"); } finally { setBusy(false); }
  }
  return (
    <Card className="max-w-2xl p-5">
      <div className="section-title">White-label branding</div>
      <p className="mt-1 text-[13px] text-muted">Show your own product name, logo and colour to everyone in this workspace, for example when an agency runs Kruvim for its clients.</p>
      {!allowed && <Callout tone="info" className="mt-4">Custom branding is available on the Business and Enterprise plans.</Callout>}
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <Field label="Product name" hint="Optional"><Input value={f.product_name} onChange={(e) => setF({ ...f, product_name: e.target.value })} placeholder="Acme Audience Lab" disabled={!allowed || !can("admin")} /></Field>
        <Field label="Accent colour" hint="Hex, e.g. #0f766e">
          <div className="flex gap-2">
            <Input value={f.accent} onChange={(e) => setF({ ...f, accent: e.target.value })} placeholder="#2155cd" disabled={!allowed || !can("admin")} />
            <input type="color" aria-label="Pick a colour" value={/^#[0-9a-f]{6}$/i.test(f.accent) ? f.accent : "#2155cd"} disabled={!allowed || !can("admin")}
              onChange={(e) => setF({ ...f, accent: e.target.value })} className="h-8 w-10 shrink-0 cursor-pointer rounded border border-line-strong bg-panel" />
          </div>
        </Field>
        <Field label="Logo URL" hint="https only" className="sm:col-span-2"><Input value={f.logo_url} onChange={(e) => setF({ ...f, logo_url: e.target.value })} placeholder="https://example.com/logo.png" disabled={!allowed || !can("admin")} /></Field>
        <Field label="Report footer" hint="Optional" className="sm:col-span-2"><Input value={f.report_footer} onChange={(e) => setF({ ...f, report_footer: e.target.value })} placeholder="Prepared by Acme for internal use" disabled={!allowed || !can("admin")} /></Field>
      </div>
      <div className="mt-5 flex gap-2">
        <Button variant="primary" loading={busy} disabled={!allowed || !can("admin")} onClick={save}>Save branding</Button>
        <Button disabled={!allowed || !can("admin")} onClick={() => setF({ product_name: "", accent: "", logo_url: "", report_footer: "" })}>Reset to Kruvim</Button>
      </div>
    </Card>
  );
}
