import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
type Accuracy = { available: boolean; accuracy_percent: number | null; n: number | null; excluded: number | null;
  confidence_interval_95: number[] | null; method: string; reason: string | null };
export default function AccuracyReport({ publicReport = false }: { publicReport?: boolean }) {
  const orgId = useAuth((s) => s.orgId);
  const q = useQuery({ queryKey: publicReport ? ["public-accuracy"] : [orgId, "accuracy"],
    queryFn: () => api<Accuracy>(publicReport ? "/public/accuracy" : "/accuracy") });
  const r = q.data;
  return <Card className="mb-5 space-y-2 p-5"><h2 className="font-semibold">{publicReport ? "Published accuracy report" : "Your A/B prediction accuracy"}</h2>
    {q.isPending ? <p role="status">Loading report…</p> : q.isError ? <p role="alert">Accuracy report could not be loaded.</p> :
      <><p className="text-lg">{r?.accuracy_percent != null ? `Kruvim picked the variant with more views ${r.accuracy_percent}% of the time across ${r.n} A/B tests.` : r?.reason || "No eligible A/B outcomes yet. No accuracy claim is available."}</p>
        {r?.confidence_interval_95 && <p className="text-sm">95% confidence interval: {r.confidence_interval_95.join("–")}% · {r.excluded} pairs excluded</p>}
        <p className="text-xs leading-relaxed text-muted">{r?.method}</p></>}
  </Card>;
}
