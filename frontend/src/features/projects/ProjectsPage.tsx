import { useMutation, useQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Page } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/overlay";
import { Card, Empty, Field, Input, Skeleton, Textarea } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Project } from "@/lib/types";
import { fmt } from "@/lib/utils";

export default function ProjectsPage() {
  const orgId = useAuth((s) => s.orgId);
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [f, setF] = useState({ name: "", description: "" });
  const q = useQuery({ queryKey: [orgId, "projects"], queryFn: () => api<Project[]>("/projects") });
  useEffect(() => { if (sp.get("new")) { setOpen(true); setSp({}); } }, [sp, setSp]);
  const create = useMutation({
    mutationFn: () => api<Project>("/projects", { json: f }),
    onSuccess: (p) => { setOpen(false); nav(`/projects/${p.id}`); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });
  const rows = useMemo(() => (q.data || []).filter((p) => !filter || `${p.name} ${p.description}`.toLowerCase().includes(filter.toLowerCase())), [q.data, filter]);
  return (
    <Page title="Projects" subtitle="Group simulations by campaign, client or channel. Background documents added to a project are used by every simulation in it."
      actions={<Button variant="primary" onClick={() => setOpen(true)}><Plus className="h-4 w-4" />New project</Button>}>
      {q.isLoading ? <Card className="space-y-2 p-4"><Skeleton /><Skeleton /><Skeleton /></Card>
        : (q.data || []).length === 0 ? <Card><Empty title="No projects yet" action={<Button variant="primary" onClick={() => setOpen(true)}>Create project</Button>}>
          A project holds simulations and the background documents that ground them.</Empty></Card>
          : (
            <Card className="overflow-hidden">
              <div className="flex items-center gap-3 border-b border-line px-3 py-2.5">
                <div className="relative w-72 max-w-full">
                  <Search className="absolute left-2.5 top-2 h-4 w-4 text-faint" />
                  <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter projects" className="pl-8" />
                </div>
                <span className="ml-auto text-xs text-muted">{rows.length} of {q.data!.length}</span>
              </div>
              <div className="overflow-x-auto">
                <table className="dt min-w-[640px]">
                  <thead><tr><th>Project</th><th className="!text-right">Simulations</th><th className="!text-right">Last activity</th><th className="!text-right">Created</th></tr></thead>
                  <tbody>{rows.map((p) => (
                    <tr key={p.id} className="hoverable" onClick={() => nav(`/projects/${p.id}`)}>
                      <td><div className="font-medium">{p.name}</div><div className="max-w-xl truncate text-xs text-muted">{p.description || "No description"}</div></td>
                      <td className="r">{fmt.n(p.simulations as number)}</td>
                      <td className="r text-muted">{fmt.ago(p.last_activity)}</td>
                      <td className="r text-muted">{fmt.day(p.created_at)}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </Card>
          )}
      <Dialog open={open} onOpenChange={setOpen} title="New project" footer={<><Button onClick={() => setOpen(false)}>Cancel</Button>
        <Button variant="primary" disabled={!f.name.trim()} loading={create.isPending} onClick={() => create.mutate()}>Create project</Button></>}>
        <div className="space-y-4">
          <Field label="Name"><Input autoFocus value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Ramadan 2027 campaign" /></Field>
          <Field label="Description" hint="Optional"><Textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} className="min-h-[72px]" /></Field>
        </div>
      </Dialog>
    </Page>
  );
}
