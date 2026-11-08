import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export function usePoolQuery<T = any>(key: unknown[], path: string, poll = false) {
  const orgId = useAuth(state => state.orgId);
  return useQuery({
    queryKey: [orgId, "data-pool", ...key],
    enabled: !!orgId,
    staleTime: 60_000,
    refetchInterval: poll ? 60_000 : false,
    retry: false,
    queryFn: async ({ signal }) => {
      const controller = new AbortController();
      const abort = () => controller.abort();
      signal.addEventListener("abort", abort, { once: true });
      const timer = setTimeout(abort, 15_000);
      try {
        return await api<T>(path, { signal: controller.signal });
      } catch (error) {
        if (controller.signal.aborted && !signal.aborted) throw new ApiError(504, "data_pool_timeout", "This data could not load in time. Try again.");
        throw error;
      } finally {
        clearTimeout(timer);
        signal.removeEventListener("abort", abort);
      }
    },
  });
}
