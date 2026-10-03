import { useQuery } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { Page } from "@/components/layout/AppShell";
import { Callout, Card, CardHeader, Stat } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn, fmt } from "@/lib/utils";

export default function UsagePage() {
  const orgId = useAuth((s) => s.orgId);
  const q = useQuery({ queryKey: [orgId, "usage"], queryFn: () => api("/usage") });
  const u = q.data;
  if (!u) return null;
  const calls = u.month.reduce((a: number, m: any) => a + m.calls, 0);
  const cost = u.month.reduce((a: number, m: any) => a + (m.cost_usd || 0), 0);
  return (
    <Page title="Usage and credits" subtitle="One credit is one LLM agent turn. Runs on your own key or a local model are not metered; runs on the Kruvim platform key draw from your monthly credit grant.">
      {!u.payment.enabled && <Callout tone="info" className="mb-5" title="Credit purchases are not enabled yet">{u.payment.note} Plans and monthly grants are active; upgrades are applied by a platform administrator for now.</Callout>}
      <Card className="grid grid-cols-2 divide-line md:grid-cols-4 md:divide-x">
        <Stat className="p-4" label="Credit balance" value={fmt.n(u.credits_balance)} sub={`${u.limits.label} plan · ${fmt.n(u.limits.monthly_credits)} per month`} />
        <Stat className="p-4" label="Model calls this month" value={fmt.n(calls)} />
        <Stat className="p-4" label="Model cost this month" value={cost ? `$${cost.toFixed(2)}` : "–"} sub="From the provider prices you set" />
        <Stat className="p-4" label="Metering" value={u.metered ? "On" : "Off"} sub={u.provider_source === "org" ? "Your own key" : u.provider_source === "dryrun" ? "Dry run" : "Platform key"} />
      </Card>
      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Card className="overflow-hidden">
          <CardHeader title="This month by activity" divider />
          <table className="dt">
            <thead><tr><th>Activity</th><th className="!text-right">Calls</th><th className="!text-right">Tokens in / out</th><th className="!text-right">Cost</th></tr></thead>
            <tbody>{u.month.map((m: any) => (
              <tr key={m.kind}><td className="capitalize">{m.kind}</td><td className="r">{fmt.n(m.calls)}</td>
                <td className="r text-muted">{fmt.k(m.input_tokens)} / {fmt.k(m.output_tokens)}</td><td className="r">{m.cost_usd ? `$${m.cost_usd.toFixed(3)}` : "–"}</td></tr>
            ))}
            {u.month.length === 0 && <tr><td colSpan={4} className="text-muted">No model usage this month.</td></tr>}</tbody>
          </table>
        </Card>
        <Card className="overflow-hidden">
          <CardHeader title="Credit ledger" divider />
          <div className="max-h-80 overflow-y-auto"><table className="dt">
            <thead><tr><th>Date</th><th>Entry</th><th className="!text-right">Change</th><th className="!text-right">Balance</th></tr></thead>
            <tbody>{u.ledger.map((l: any, i: number) => (
              <tr key={i}><td className="num whitespace-nowrap text-muted">{fmt.date(l.at)}</td><td className="capitalize">{l.reason.replace(/_/g, " ")}</td>
                <td className={cn("r", l.delta >= 0 ? "text-pos" : "text-neg")}>{l.delta >= 0 ? "+" : ""}{fmt.n(l.delta)}</td><td className="r text-muted">{fmt.n(l.balance_after)}</td></tr>
            ))}</tbody>
          </table></div>
        </Card>
      </div>
      <h2 className="mb-3 mt-8 text-base font-semibold">Plans</h2>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Object.entries(u.plans).map(([k, p]: any) => (
          <Card key={k} className={cn("p-5", u.plan === k && "border-brand")}>
            <div className="flex items-center justify-between"><div className="text-[14px] font-semibold">{p.label}</div>{u.plan === k && <span className="text-xs font-medium text-brand">Current plan</span>}</div>
            <ul className="mt-3 space-y-1.5 text-[13px] text-muted">
              {[`${fmt.n(p.monthly_credits)} credits / month`, `up to ${fmt.n(p.max_voice)} voice agents`, `up to ${fmt.n(p.max_crowd)} crowd agents`, `${p.max_hours}h simulations`,
                `${p.max_concurrent} concurrent runs`, `${p.max_members >= 10000 ? "unlimited" : p.max_members} members`].map((x) => <li key={x} className="flex gap-2"><Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-pos" />{x}</li>)}
            </ul>
          </Card>
        ))}
      </div>
    </Page>
  );
}
