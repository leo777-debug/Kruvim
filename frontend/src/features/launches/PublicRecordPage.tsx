import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { Logo } from "@/components/layout/Logo";
import { Badge, Callout, Card, CardHeader } from "@/components/ui/primitives";
import { LoadError, LoadingBlock } from "@/components/ui/states";
import { api, ApiError } from "@/lib/api";
import { fmt } from "@/lib/utils";
import { Calibration, predictionText, SummaryCards, type Summary, type TrackRecord } from "./TrackRecordPage";

/** The public scoreboard: forecasts their owners chose to publish, locked before the outcome, scored against a baseline. */
export default function PublicRecordPage() {
  const q = useQuery({ queryKey: ["public-track-record"], queryFn: () => api<{ summary: Summary; records: TrackRecord[] }>("/public/track-record"),
    retry: false, meta: { silent: true } });
  const unpublished = q.error instanceof ApiError && q.error.status === 404;
  return (
    <div className="min-h-full bg-bg">
      <header className="flex h-14 items-center gap-2 px-6"><Logo className="h-[22px] w-[22px]" /><span className="text-[15px] font-semibold">Kruvim</span></header>
      <main className="mx-auto max-w-5xl space-y-5 px-4 pb-16 pt-6">
        <div>
          <h1 className="text-xl font-semibold">Kruvim's track record</h1>
          <p className="mt-1 max-w-3xl text-[13px] text-muted">Every forecast here was locked, with a cryptographic hash, before its outcome was known, then scored against a simple baseline. Nothing is removed: voided forecasts stay listed. Results are simulations, not advice.</p>
        </div>
        {unpublished ? <Callout tone="info" title="Not published yet">The public scoreboard opens once enough forecasts have resolved. The hash ledger that proves when each forecast was locked is already public.</Callout>
          : q.isError ? <LoadError error={q.error} what="the track record" onRetry={() => q.refetch()} />
          : !q.data ? <LoadingBlock label="Loading the track record" />
          : <>
            <SummaryCards summary={q.data.summary} />
            <Calibration summary={q.data.summary} />
            <Card className="overflow-hidden">
              <CardHeader title="Forecasts" divider />
              <ul className="divide-y divide-line">{q.data.records.map((r) => (
                <li key={r.id} className="space-y-1 p-4 text-[13px]">
                  <div className="flex flex-wrap items-center gap-2 font-medium">{r.question}<Badge tone={r.status === "resolved" ? "pos" : r.status === "void" ? "neg" : "brand"}>{r.status}</Badge></div>
                  <div className="text-muted">Predicted {predictionText(r)} · baseline {r.baseline_method} · resolves {fmt.day(r.resolves_on)}{r.outcome != null ? ` · outcome ${r.outcome}` : ""}</div>
                  {r.prediction_hash && <div className="text-2xs text-muted">Locked {fmt.date(r.locked_at)} · <span className="mono">sha256 {r.prediction_hash}</span></div>}
                  {r.excluded.length > 0 && <div className="text-2xs text-muted">Doesn't count: {r.excluded.join("; ")}</div>}
                </li>
              ))}</ul>
            </Card>
          </>}
        <p className="flex items-start gap-2 text-xs text-muted"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />Verify it yourself: the <a className="text-brand" href="/api/v1/public/ledger">public ledger</a> lists every lock and resolution; each entry's SHA-256 covers the previous entry, so no past forecast can be changed without breaking the chain.</p>
      </main>
    </div>
  );
}
