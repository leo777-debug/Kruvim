import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { platformName } from "@/lib/utils";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, Field, Input } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Connections } from "@/features/audiences/MyAudiencePage";
import type { Simulation } from "@/lib/types";
type Post = { id: string; variant: string; post_id: string; metrics: { views?: number; retention?: number; engagement_rate?: number };
  synced_at: string | null; last_error: string | null };
export default function PublishedPosts({ sim }: { sim: Simulation }) {
  const orgId = useAuth((s) => s.orgId);
  const qc = useQueryClient();
  const accounts = useQuery({ queryKey: [orgId, "social"], queryFn: () => api<Connections>("/social/connections") });
  const posts = useQuery({ queryKey: [orgId, "published", sim.id], queryFn: () => api<Post[]>(`/simulations/${sim.id}/published-posts`) });
  const [variant, setVariant] = useState("A");
  const [postId, setPostId] = useState("");
  const [busy, setBusy] = useState(false);
  const connection = accounts.data?.connections.find((x) => x.connected && x.platform === sim.content?.platform);
  async function mutate(path: string, method: string, json?: unknown) {
    setBusy(true);
    try {
      await api(path, { method, ...(json ? { json } : {}) });
      await qc.invalidateQueries({ queryKey: [orgId, "published", sim.id] });
      toast.success("Published post updated"); setPostId("");
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not update published post"); }
    finally { setBusy(false); }
  }
  return <Card className="space-y-3 p-5"><h2 className="font-semibold">Connect real outcomes automatically</h2>
    <p className="text-sm text-muted">Link each published post once. Analytics then sync on a schedule and update Calibration. Public accuracy uses both variants' views measured after seven days.</p>
    {(posts.isError || accounts.isError) && <p role="alert">Could not load published post connections.</p>}
    {connection ? <div className="flex flex-wrap items-end gap-3">
      <Field label="Variant"><select className="rounded border border-line bg-panel p-2" value={variant} onChange={(e) => setVariant(e.target.value)} aria-label="Published variant"><option>A</option>{sim.results?.ab && <option>B</option>}</select></Field>
      <Field label="Published post ID"><Input value={postId} onChange={(e) => setPostId(e.target.value)} placeholder="Platform post or video ID" /></Field>
      <Button loading={busy} disabled={busy || !postId.trim()} onClick={() => mutate(`/simulations/${sim.id}/published-posts`, "POST", { connection_id: connection.id, variant, post_id: postId.trim() })}>Link post</Button>
    </div> : <Link className="text-sm text-brand" to="/my-audience">Connect your {platformName(sim.content?.platform)} analytics</Link>}
    {!!posts.data?.length && <div className="overflow-x-auto"><table className="dt"><thead><tr><th>Variant</th><th>Post</th><th>Views</th><th>Engagement</th><th>Retention</th><th>Status</th><th /></tr></thead><tbody>
      {posts.data.map((p) => <tr key={p.id}><td>{p.variant}</td><td>{p.post_id}</td><td>{p.metrics.views?.toLocaleString() ?? "Unavailable"}</td>
        <td>{p.metrics.engagement_rate != null ? `${p.metrics.engagement_rate}%` : "Unavailable"}</td><td>{p.metrics.retention != null ? `${p.metrics.retention}%` : "Unavailable"}</td>
        <td>{p.last_error || (p.synced_at ? `Synced ${new Date(p.synced_at).toLocaleDateString()}` : "Awaiting scheduled sync")}</td>
        <td><Button disabled={busy} onClick={() => mutate(`/simulations/${sim.id}/published-posts/${p.id}`, "DELETE")}>Remove</Button></td></tr>)}
    </tbody></table></div>}
  </Card>;
}
