import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Asset } from "@/lib/types";
import { prepareFile } from "@/lib/local/prepare";
import type { PreparedFile } from "@/lib/local/types";
import { Button } from "./ui/button";
import { Dialog } from "./ui/overlay";
import { LocalNotice, LocalReview } from "./LocalReview";

export function LocalDocuments({ project, onSaved }: { project: () => Promise<string>; onSaved: (asset: Asset) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const controller = useRef<AbortController>();
  const [progress, setProgress] = useState(""); const [error, setError] = useState("");
  const [review, setReview] = useState<{ name: string; value: PreparedFile }>();
  const [sending, setSending] = useState(false);
  useEffect(() => () => controller.current?.abort(), []);
  async function select(file?: File) {
    if (!file) return;
    const ctrl = new AbortController(); controller.current = ctrl; setError(""); setProgress("Reading document locally");
    try { setReview({ name: file.name, value: await prepareFile(file, ctrl.signal, setProgress) }); }
    catch (e) { setError(e instanceof Error ? e.message : "Local extraction failed. Paste text instead."); }
    finally { setProgress(""); }
  }
  async function send() {
    if (!review) return; setSending(true);
    try {
      const asset = await api<Asset>(`/projects/${await project()}/assets/extracted-text`, { json: { filename: review.name, text: review.value.text } });
      onSaved(asset); setReview(undefined); toast.success("Extracted text added. Original document stayed on this device.");
    } catch (e) { setError(e instanceof Error ? e.message : "Could not save extracted text."); }
    finally { setSending(false); }
  }
  return <div className="space-y-2">
    <Button size="sm" disabled={!!progress || sending} onClick={() => input.current?.click()}>Choose document locally</Button>
    <input ref={input} aria-label="Local background document" type="file" accept=".pdf,.docx,.md,.txt,.csv,.json" className="hidden" onChange={e => { void select(e.target.files?.[0]); e.target.value = ""; }} />
    {!!progress && <div role="status">{progress} <Button size="sm" onClick={() => controller.current?.abort()}>Cancel local processing</Button></div>}
    {!!error && <p role="alert" className="text-sm text-neg">{error}</p>}
    <LocalNotice />
    <Dialog open={!!review} onOpenChange={open => { if (!open && !sending) setReview(undefined); }} title="Review background text" description="Only this extracted text will be saved in the cloud and used as simulation context."
      footer={<><Button disabled={sending} onClick={() => setReview(undefined)}>Discard</Button><Button disabled={!review?.value.text.trim()} loading={sending} onClick={send}>Send reviewed text to cloud</Button></>}>
      {review && <LocalReview value={review.value} set={value => setReview({ ...review, value })} />}
    </Dialog>
  </div>;
}
