import type { UseQueryResult } from "@tanstack/react-query";
import { AlertTriangle, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";

/** What went wrong, in words a user can act on. Never a stack trace. */
export function errorText(error: unknown, what = "this"): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return `You don't have access to ${what}. Ask a workspace admin.`;
    if (error.status === 404) return `${what[0].toUpperCase()}${what.slice(1)} was not found. It may have been removed.`;
    if (error.status === 429) return "Too many requests right now. Wait a minute and try again.";
    return error.message;
  }
  if (error instanceof TypeError) return "Kruvim could not be reached. Check your connection and try again.";
  return `Something went wrong while loading ${what}.`;
}

export function LoadingBlock({ rows = 4, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-live="polite" className="space-y-2">
      <span className="sr-only">{label}…</span>
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className={i === 0 ? "h-8 w-1/3" : "h-14"} />)}
    </div>
  );
}

export function LoadError({ error, what, onRetry }: { error: unknown; what?: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-lg border border-neg/25 bg-neg/[0.04] p-4 sm:flex-row sm:items-center">
      <AlertTriangle className="h-5 w-5 shrink-0 text-neg" aria-hidden />
      <div className="flex-1 text-[13px]">
        <div className="font-medium">Couldn't load {what || "this page"}</div>
        <div className="text-muted">{errorText(error, what)}</div>
      </div>
      {onRetry && <Button size="sm" onClick={onRetry}><RefreshCw className="h-3.5 w-3.5" />Try again</Button>}
    </div>
  );
}

/** Loading, error and ready states for a query, so no screen is ever blank or silently broken. */
export function QueryGate<T>({ query, what, rows, children }: { query: UseQueryResult<T>; what?: string; rows?: number; children: (data: T) => ReactNode }) {
  if (query.isError && query.data === undefined) return <LoadError error={query.error} what={what} onRetry={() => query.refetch()} />;
  if (query.data === undefined) return <LoadingBlock rows={rows} label={what ? `Loading ${what}` : "Loading"} />;
  return <>{children(query.data)}</>;
}
