import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, Select } from "@/components/ui/overlay";
import { Card, Field } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt } from "@/lib/utils";

type Summary = { agents: number; familiarity: number; affinity: number; fatigue: number; fatigue_warning: boolean;
  subjects: string[]; retention_days: number; cap_per_agent: number };

export function AudienceMemory() {
  const { orgId, orgs } = useAuth();
  const admin = ["owner", "admin"].includes(orgs.find((org) => org.id === orgId)?.role || "");
  const qc = useQueryClient();
  const [subject, setSubject] = useState("all");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const all = useQuery({ queryKey: [orgId, "audience-memory"], queryFn: () => api<Summary>("/my-audience/agent-memory"), refetchInterval: 30_000 });
  const selected = useQuery({ queryKey: [orgId, "audience-memory", subject], queryFn: () => api<Summary>(`/my-audience/agent-memory?subject=${encodeURIComponent(subject)}`), enabled: subject !== "all" });
  const data = subject === "all" ? all.data : selected.data;
  async function reset() {
    setBusy(true);
    try {
      await api("/my-audience/agent-memory/reset", { json: { confirmed: true, subject: subject === "all" ? null : subject } });
      await Promise.all([qc.invalidateQueries({ queryKey: [orgId, "audience-memory"] }), qc.invalidateQueries({ queryKey: [orgId, "my-audience"] }), qc.invalidateQueries({ queryKey: ["agent"] })]);
      toast.success("Simulated audience memory reset");
      setConfirm(false);
    } catch (error) { toast.error(error instanceof ApiError ? error.message : "Could not reset memory"); }
    finally { setBusy(false); }
  }
  return <Card className="mt-5 space-y-3 p-5">
    <h2 className="font-semibold">Audience memory</h2>
    <p className="text-sm text-muted">Simulated memories and creator affinity, never real follower data.</p>
    <Field label="Creator history"><Select value={subject} onChange={setSubject} options={[{ value: "all", label: "All creators" },
      ...(all.data?.subjects || []).map((value) => ({ value, label: value.replace(/^creator:/, "") }))]} /></Field>
    {(all.isError || selected.isError) ? <p role="alert" className="text-sm text-neg">Could not load audience memory. <Button onClick={() => { all.refetch(); if (subject !== "all") selected.refetch(); }}>Retry</Button></p> :
      !data ? <p className="text-sm text-muted">Loading simulated memory…</p> : <>
        <div className="grid gap-3 text-sm sm:grid-cols-3"><p><strong>{fmt.n(data.agents)}</strong> agents remember you</p>
          <p>Average familiarity <strong>{data.familiarity.toFixed(1)}</strong></p><p>Average affinity <strong>{data.affinity.toFixed(2)}</strong></p></div>
        <p className="text-xs text-muted">Fatigue {fmt.pct(data.fatigue)} · Up to {data.cap_per_agent} memories per agent · {data.retention_days} days retention</p>
        {data.fatigue_warning && <p role="status" className="text-sm text-warn">Audience fatigue is high. Try a different topic or leave more time between similar posts.</p>}
      </>}
    {admin && <Button disabled={busy || !data?.agents} onClick={() => setConfirm(true)}>Reset audience memory</Button>}
    <Dialog open={confirm} onOpenChange={setConfirm} title="Reset simulated audience memory?"
      description={`Delete ${subject === "all" ? "all creators'" : subject.replace(/^creator:/, "") + "'s"} retained memories and affinity in this workspace. New tests start without this history. Existing run records remain auditable.`}
      footer={<><Button disabled={busy} onClick={() => setConfirm(false)}>Cancel</Button><Button variant="primary" loading={busy} onClick={reset}>Reset audience memory</Button></>}>
      <p className="text-sm text-muted">This action is recorded in the workspace audit log.</p>
    </Dialog>
  </Card>;
}
