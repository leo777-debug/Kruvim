import { useQuery } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

interface Alerts { unread: number; items: { id: string; title: string; body: string; read: boolean; created_at: string; simulation_id: string | null }[] }
export function useAlerts() {
  const orgId = useAuth((s) => s.orgId);
  return useQuery({ queryKey: [orgId, "alerts"], queryFn: () => api<Alerts>("/alerts"), refetchInterval: 30000, enabled: !!orgId });
}
export function AlertsBell() {
  const q = useAlerts();
  const n = q.data?.unread || 0;
  return <Link to="/monitoring#alerts" aria-label={`Alerts${n ? `, ${n} unread` : ""}`} className="ml-auto flex items-center gap-1 rounded p-1.5 text-muted hover:bg-raised"><Bell className="h-4 w-4" />{n > 0 && <span className="rounded bg-brand px-1 text-xs text-brand-fg">{n > 99 ? "99+" : n}</span>}</Link>;
}

