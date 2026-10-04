import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { platformName } from "@/lib/utils";
import { toast } from "sonner";
import { Page } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Card, Field, Input, Switch, Textarea } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { AudienceMemory } from "./AudienceMemory";

type Split = { countries: Record<string, number>; ages: Record<string, number>; genders: Record<string, number> };
type Connection = { id: string; platform: string; account_name: string; connected: boolean; share_accuracy: boolean;
  last_sync_at: string | null; last_error: string | null; audience: Partial<Split> & { kind?: string; limitations?: string } };
type Provider = { platform: string; configured: boolean; limitations: string };
export type Connections = { connections: Connection[]; providers: Provider[] };
function parsePercentages(text: string): Record<string, number> {
  const result: Record<string, number> = {};
  for (const row of text.split(/[\n,;]+/).map((s) => s.trim()).filter(Boolean)) {
    const match = row.match(/^(.+?)\s*[:=\s]\s*(\d+(?:\.\d+)?)\s*%?$/);
    if (!match || result[match[1].trim()] !== undefined) throw new Error("Use one category and percentage per line, without duplicates.");
    result[match[1].trim()] = Number(match[2]);
  }
  return result;
}
const displaySplit = (values: Record<string, number>) => Object.entries(values || {}).map(([key, value]) => `${key}: ${value}%`).join("\n");

export default function MyAudiencePage() {
  const orgId = useAuth((s) => s.orgId);
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const accounts = useQuery({ queryKey: [orgId, "social"], queryFn: () => api<Connections>("/social/connections"), refetchInterval: 60_000 });
  const profile = useQuery({ queryKey: [orgId, "my-audience"], queryFn: () => api<{ profile: { split: Split; label: string; source: string } | null;
    memory: { summary?: string; real_summary?: string; note?: string; observations?: { simulation_id: string; title: string; score: number; dry: boolean }[] } }>("/my-audience") });
  const [countries, setCountries] = useState("SA: 70%\nAE: 30%");
  const [ages, setAges] = useState("18-24: 60%\n25-34: 40%");
  const [genders, setGenders] = useState("female: 55%\nmale: 45%");
  const [label, setLabel] = useState("My audience");
  const [busy, setBusy] = useState<string | null>(null);
  async function action(key: string, path: string, method = "POST", json?: unknown) {
    setBusy(key);
    try {
      const result = await api<{ url?: string }>(path, { method, ...(json !== undefined ? { json } : {}) });
      if (result?.url) { window.location.assign(result.url); return; }
      await Promise.all([qc.invalidateQueries({ queryKey: [orgId, "social"] }), qc.invalidateQueries({ queryKey: [orgId, "my-audience"] })]);
      toast.success("Updated");
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not update audience analytics"); }
    finally { setBusy(null); }
  }
  return <Page title="My audience" subtitle="Connect real outcomes automatically and test content against your own audience. Only aggregate analytics are collected.">
    {params.get("connection") && <Card className="mb-4 p-4" role="status">{params.get("connection") === "connected" ? "Account connected. Sync analytics to load its breakdown." : "Account connection failed. Check permissions and try again."}</Card>}
    {(accounts.isError || profile.isError) && <Card className="mb-4 p-4" role="alert">Could not load audience data. <Button onClick={() => { accounts.refetch(); profile.refetch(); }}>Retry</Button></Card>}
    <Card className="overflow-x-auto">
      <table className="dt account-table"><thead><tr><th>Platform</th><th>Account</th><th>Available analytics</th><th>Actions</th></tr></thead><tbody>
        {accounts.data?.providers.map((provider) => {
          const c = accounts.data.connections.find((x) => x.platform === provider.platform);
          return <tr key={provider.platform}><td data-label="Platform">{platformName(provider.platform)}</td><td data-label="Account">{c?.connected ? c.account_name : "Not connected"}</td>
            <td data-label="Available analytics" className="max-w-md whitespace-normal"><p>{provider.limitations}</p>{c?.last_error && <p role="alert" className="text-neg">{c.last_error}</p>}
              {c?.last_sync_at && <p className="text-xs text-muted">Last synced {new Date(c.last_sync_at).toLocaleString()}</p>}</td>
            <td data-label="Actions"><div className="flex flex-wrap gap-2"><Button disabled={!provider.configured || busy !== null} loading={busy === provider.platform}
              onClick={() => action(provider.platform, `/social/${provider.platform}/connect`)}>{c?.connected ? "Reconnect" : provider.configured ? "Connect" : "Setup required"}</Button>
              {c?.connected && <><Button disabled={busy !== null} onClick={() => action(c.id, `/social/connections/${c.id}/sync`)} loading={busy === c.id}>Sync now</Button>
                <Button disabled={busy !== null} onClick={() => action(`use-${c.id}`, `/social/connections/${c.id}/use-audience`)}>Use breakdown</Button>
                <Button disabled={busy !== null} onClick={() => action(`delete-${c.id}`, `/social/connections/${c.id}`, "DELETE")}>Disconnect</Button></>}
            </div>{c?.connected && <div className="mt-2"><Switch checked={c.share_accuracy} disabled={busy !== null}
              onChange={(v) => action(`consent-${c.id}`, `/social/connections/${c.id}/consent`, "PATCH", { share_accuracy: v })}
              label="Contribute anonymous A/B accuracy" /></div>}</td></tr>;
        })}
      </tbody></table>{accounts.isPending && <p className="p-4 text-muted" role="status">Loading accounts…</p>}
    </Card>
    <div className="mt-5 grid gap-5 lg:grid-cols-2">
      <Card className="space-y-4 p-5"><h2 className="font-semibold">Follower breakdown</h2>
        <p className="text-sm text-muted">Countries use two-letter codes. Each supplied country, age or gender split must add to 100%. The simulator supports ages 16–70 and its listed countries; coverage limitations appear in the results.</p>
        {profile.data?.profile && <div className="space-y-2"><p className="text-sm">Current: {profile.data.profile.label} · {profile.data.profile.source}</p>
          <table className="dt"><thead><tr><th>Breakdown</th><th>Percentages</th></tr></thead><tbody>{Object.entries(profile.data.profile.split).map(([key, values]) =>
            <tr key={key}><td className="capitalize">{key}</td><td className="whitespace-normal">{Object.entries(values).map(([category, percent]) => `${category}: ${percent}%`).join(", ") || "Unavailable"}</td></tr>)}</tbody></table>
          <Button onClick={() => { const p = profile.data!.profile!; setLabel(p.label); setCountries(displaySplit(p.split.countries)); setAges(displaySplit(p.split.ages)); setGenders(displaySplit(p.split.genders)); }}>Edit current breakdown</Button></div>}
        <Field label="Audience name"><Input value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
        <Field label="Country percentages" help="One country code and percentage per line, for example SA: 70%. Leave a split blank if unavailable.">
          <Textarea value={countries} onChange={(e) => setCountries(e.target.value)} /></Field>
        <Field label="Age percentages" help="One age band and percentage per line, for example 18-24: 60%."><Textarea value={ages} onChange={(e) => setAges(e.target.value)} /></Field>
        <Field label="Gender percentages" help="Use female, male or unknown, followed by the percentage."><Textarea value={genders} onChange={(e) => setGenders(e.target.value)} /></Field>
        <Button variant="primary" disabled={busy !== null} loading={busy === "save"} onClick={() => {
          try { const split = { countries: parsePercentages(countries), ages: parsePercentages(ages), genders: parsePercentages(genders) }; action("save", "/my-audience", "PUT", { label, split }); }
          catch { toast.error("Use one category and percentage per line, without duplicates."); }
        }}>Save breakdown</Button>
      </Card>
      <Card className="space-y-3 p-5"><h2 className="font-semibold">What your audience rewards</h2>
        <p className="text-sm text-muted">{profile.data?.memory.note || "Complete a simulation to build your workspace's audience memory."}</p>
        <p className="text-sm leading-relaxed">{profile.data?.memory.summary}</p>
        <p className="text-sm leading-relaxed">{profile.data?.memory.real_summary}</p>
        <table className="dt"><thead><tr><th>Test</th><th>Opinion</th><th>Mode</th></tr></thead><tbody>{profile.data?.memory.observations?.map((x) =>
          <tr key={x.simulation_id}><td><Link className="text-brand" to={`/simulations/${x.simulation_id}`}>{x.title}</Link></td><td>{x.score}/10</td><td>{x.dry ? "Dry run" : "Model"}</td></tr>)}</tbody></table>
        <p className="text-xs text-muted">Workspace observations complement each agent's individual simulated memory.</p>
        <p className="text-xs text-muted">When creating a test, choose “Match my audience.” Completed tests can be linked to published post IDs from their Overview.</p>
      </Card>
    </div>
    <AudienceMemory />
  </Page>;
}
