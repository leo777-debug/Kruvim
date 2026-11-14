import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CreditCard, ExternalLink, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Badge, Callout, Card, Input, Progress } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { can, useAuth } from "@/lib/auth";
import { fmt } from "@/lib/utils";

export interface BillingState {
  paused?: boolean;
  enabled: boolean;
  configured: boolean;
  environment: "test_mode" | "live_mode";
  active: boolean;
  status: string;
  review_required: boolean;
  seats: number;
  members: number;
  period_end: string | null;
  can_manage: boolean;
  monthly_price_aed: number;
  topup_price_aed: number;
  monthly_credits: number;
  topup_credits: number;
  monthly_remaining: number;
  purchased_remaining: number;
  available: number;
  note: string;
}

export function useBilling(poll = false) {
  const orgId = useAuth((s) => s.orgId);
  return useQuery({ queryKey: [orgId, "billing"], queryFn: () => api<BillingState>("/billing"),
    enabled: !!orgId, staleTime: 10_000, refetchInterval: poll ? 3000 : 30_000, retry: 1 });
}

export function BillingNotice() {
  const q = useBilling();
  if (!q.data?.enabled || (q.data.active && q.data.available > 0)) return null;
  return <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-panel px-5 py-3 text-sm" role="status">
    <span>{q.data.active ? "Your usage credits are used up. Add credits to continue testing." : "Subscribe to start testing your content with Kruvim."}</span>
    <Link className="font-semibold text-brand underline underline-offset-4" to="/usage">View billing</Link>
  </div>;
}

export default function BillingPanel() {
  const [params] = useSearchParams();
  const returned = params.get("checkout") === "returned";
  const q = useBilling(returned);
  const cache = useQueryClient();
  const orgId = useAuth((s) => s.orgId);
  const [selectedSeats, setSeats] = useState(1);
  const owner = can("owner");
  const b = q.data;
  const seats = Math.max(selectedSeats, b?.seats ?? 1, b?.members ?? 1);
  const action = useMutation({ mutationFn: async (kind: "subscription" | "topup" | "portal") => {
    const result = await api<{ url: string }>(kind === "portal" ? "/billing/portal" : "/billing/checkout",
      { json: kind === "portal" ? {} : { kind, seats } });
    const url = new URL(result.url);
    if (url.protocol !== "https:" || !(url.hostname === "dodopayments.com" || url.hostname.endsWith(".dodopayments.com"))) {
      throw new Error("The payment link could not be opened. Please try again.");
    }
    window.location.assign(url.href);
  }});
  if (q.isError) return <Callout tone="warn" title="Billing could not load"><p>{q.error.message}</p>
    <Button type="button" className="mt-2" onClick={() => q.refetch()}>Try again</Button></Callout>;
  if (!b) return <p className="text-sm text-muted" role="status">Loading billing…</p>;
  if (!b.enabled) return null;
  const used = b.active ? Math.max(0, b.monthly_credits - b.monthly_remaining) : 0;
  const disabled = action.isPending || !b.configured || !owner;
  return <div className="space-y-5">
    {b.environment === "test_mode" && b.configured && <Callout tone="info" title="Test checkout">This checkout is in test mode. No real payments are collected.</Callout>}
    {!b.configured && <Callout tone="info" title="Payments are being set up">{b.note}</Callout>}
    {returned && <Callout tone="info" title="Checking payment status">Payment confirmation can take a few minutes. Your subscription and credits update after confirmation.
      <Button type="button" className="ml-3" onClick={() => {
        cache.invalidateQueries({ queryKey: [orgId, "billing"] });
        cache.invalidateQueries({ queryKey: [orgId, "usage"] });
      }}><RefreshCw className="h-3.5 w-3.5" />Refresh</Button></Callout>}
    {params.get("checkout") === "cancelled" && <Callout tone="info" title="Checkout closed">You can return to checkout whenever you are ready.</Callout>}
    {b.review_required && <Callout tone="warn" title="Billing needs attention">Please contact support about a refunded or disputed payment before running more simulations.</Callout>}
    {action.error && <Callout tone="warn" title="Payment could not start">{action.error.message}</Callout>}
    {!owner && <p className="text-sm text-muted">Your workspace owner manages subscriptions and credit purchases.</p>}
    <div className="grid gap-5 md:grid-cols-2">
      <Card className="space-y-4 p-5">
        <div className="flex items-center justify-between gap-3"><h2 className="font-semibold">Kruvim membership</h2>
          <Badge tone={b.active ? "pos" : "outline"}>{b.active ? "Active" : b.status.replace(/_/g, " ")}</Badge></div>
        <div><span className="text-3xl font-semibold">AED {b.monthly_price_aed}</span><span className="text-sm text-muted"> / person / month</span></div>
        <p className="text-sm text-muted">Test your content, read audience reactions, and explore reports. Usage draws from your included credits; larger tests use more.</p>
        {!b.can_manage && <label className="block text-sm">Paid seats<Input className="mt-1 max-w-28" aria-label="Number of paid seats" type="number"
          min={Math.max(1, b.members)} max={1000} value={seats} disabled={!owner || action.isPending}
          onChange={(e) => setSeats(Math.min(1000, Math.max(b.members, Number(e.target.value) || 1)))} /></label>}
        <p className="text-sm">{b.can_manage ? b.seats : seats} seat{(b.can_manage ? b.seats : seats) !== 1 ? "s" : ""} · AED {b.monthly_price_aed * (b.can_manage ? b.seats : seats)} / month</p>
        {b.period_end && <p className="text-xs text-muted">Paid access through {fmt.date(b.period_end)}. Manage renewal and cancellation in the billing portal.</p>}
        <div className="flex flex-wrap gap-2">
          {(!b.can_manage || ["cancelled", "expired", "failed"].includes(b.status)) && <Button type="button" variant="primary" disabled={disabled}
            onClick={() => action.mutate("subscription")}><CreditCard className="h-4 w-4" />{action.isPending ? "Opening checkout…" : "Subscribe"}</Button>}
          {b.can_manage && <Button type="button" disabled={disabled} onClick={() => action.mutate("portal")}>
            <ExternalLink className="h-4 w-4" />Manage billing</Button>}
        </div>
        <p className="text-xs text-muted">Checkout shows the final total, including applicable tax. Payments are handled securely by Dodo Payments.</p>
      </Card>
      <Card className="space-y-4 p-5">
        <h2 className="font-semibold">Your usage credits</h2>
        <div className="text-3xl font-semibold">{fmt.n(b.available)} <span className="text-sm font-normal text-muted">available</span></div>
        <div><div className="mb-2 flex justify-between text-xs text-muted"><span>Monthly credits used</span><span>{fmt.n(used)} / {fmt.n(b.monthly_credits)}</span></div>
          <Progress value={b.monthly_credits ? Math.min(100, used / b.monthly_credits * 100) : 0} /></div>
        <p className="text-sm text-muted">{fmt.n(b.purchased_remaining)} purchased credits. Monthly credits are used first and reset after a successful renewal. Purchased credits do not expire.</p>
        <div className="rounded-lg border border-line p-4"><div className="font-medium">{fmt.n(b.topup_credits)} extra credits · AED {b.topup_price_aed}</div>
          <p className="mb-3 mt-1 text-xs text-muted">Add usage to your current membership. Tests pause when the available allowance is exhausted.</p>
          <Button type="button" disabled={disabled || !b.active} onClick={() => action.mutate("topup")}>Buy extra credits</Button></div>
        <p className="text-xs text-muted">Credits measure usage, rather than a fixed number of simulations. Paused tests keep their progress.</p>
      </Card>
    </div>
  </div>;
}
