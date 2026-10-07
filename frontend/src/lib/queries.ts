import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { useAuth } from "./auth";
import type { Reference } from "./types";

export function useReference() {
  return useQuery({ queryKey: ["reference"], queryFn: () => api<Reference>("/reference"), staleTime: Infinity });
}

export function useOrgKey(...rest: unknown[]) {
  const orgId = useAuth((s) => s.orgId);
  return [orgId, ...rest];
}
