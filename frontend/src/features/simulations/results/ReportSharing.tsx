import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, Select } from "@/components/ui/overlay";
import { Field, Input } from "@/components/ui/primitives";
import { api, downloadFile } from "@/lib/api";
import { can } from "@/lib/auth";
import { fmt } from "@/lib/utils";

export function ReportSharing({ simId }: { simId: string }) {
  const [open, setOpen] = useState(false);
  const [days, setDays] = useState("7");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState("");
  const links = useQuery({queryKey: ["result-shares", simId], enabled: open, queryFn: () => api<any[]>(`/simulations/${simId}/shares`)});
  async function download(format: string) {
    setBusy(format);
    try { await downloadFile(`/simulations/${simId}/report/download?format=${format}`, `report.${format}`); }
    catch (e) { toast.error(e instanceof Error ? e.message : "Download failed"); }
    finally { setBusy(""); }
  }
  async function create() {
    setBusy("share");
    try { const link = await api(`/simulations/${simId}/shares`, {json: {days: Number(days)}}); setUrl(link.url); links.refetch(); }
    catch (e) { toast.error(e instanceof Error ? e.message : "Unable to share"); }
    finally { setBusy(""); }
  }
  async function revoke(id: string) {
    try { await api(`/simulations/${simId}/shares/${id}`, {method:"DELETE"}); setUrl(""); links.refetch(); }
    catch (e) { toast.error(e instanceof Error ? e.message : "Unable to revoke"); }
  }
  return <><div className="mb-4 flex flex-wrap gap-2">
    {[["pdf", "PDF"], ["docx", "Word"], ["md", "Markdown"]].map(([format, label]) => <Button key={format} size="sm" disabled={!!busy} loading={busy === format} onClick={() => download(format)}>Download {label}</Button>)}
    <Button size="sm" onClick={() => setOpen(true)}>Share results</Button>
  </div><Dialog open={open} onOpenChange={setOpen} title="Share results" description="Anyone with the link can read this run's results and report until it expires or you revoke it.">
    <div className="space-y-4"><Field label="Link expires after"><Select value={days} onChange={setDays} options={[{value:"1",label:"1 day"},{value:"7",label:"7 days"},{value:"30",label:"30 days"}]} /></Field>
      <Button disabled={!can("member") || !!busy} loading={busy === "share"} variant="primary" onClick={create}>Create read-only link</Button>
      {url && <Field label="Share link"><Input value={url} readOnly /><Button className="mt-2" size="sm" onClick={async () => {try {await navigator.clipboard.writeText(url); toast.success("Link copied");} catch {toast.error("Select the link and copy it");}}}>Copy link</Button></Field>}
      <div className="space-y-2">{links.data?.map((link) => <div key={link.id} className="flex flex-wrap items-center gap-2 text-xs"><span className="mr-auto">{link.revoked_at ? "Revoked" : new Date(link.expires_at) <= new Date() ? "Expired" : `Expires ${fmt.date(link.expires_at)}`} · {link.view_count} views</span>
        {!link.revoked_at && can("member") && <Button size="sm" variant="danger" onClick={() => revoke(link.id)}>Revoke</Button>}
      </div>)}</div>
    </div>
  </Dialog></>;
}
