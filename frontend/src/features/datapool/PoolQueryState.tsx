import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/primitives";

export function PoolQueryState({ query, label }: { query: { isPending: boolean; isError: boolean; error: Error | null; refetch: () => unknown }; label: string }) {
  if (query.isError) return <Callout tone="warn" title={`${label} could not load`}>
    <p>{query.error?.message || "The server could not return this data."}</p>
    <Button className="mt-2" onClick={() => query.refetch()}>Try again</Button>
  </Callout>;
  if (query.isPending) return <p role="status" className="p-4 text-sm text-muted">Loading {label.toLowerCase()}…</p>;
  return null;
}
