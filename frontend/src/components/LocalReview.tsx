import type { PreparedFile } from "@/lib/local/types";
import { LOCAL_HELP, PRIVACY } from "@/lib/local/types";
import { localLimits } from "@/lib/local/limits";

export function LocalNotice() { return <div className="space-y-2"><p className="text-xs text-muted">{localLimits().explanation}</p><details className="rounded border border-line p-3 text-xs text-muted"><summary>Local processing, limits and downloads</summary><p className="mt-2">{PRIVACY}</p><p className="mt-2">{LOCAL_HELP}</p></details></div>; }

export function LocalReview({ value, set }: { value: PreparedFile; set: (v: PreparedFile) => void }) {
  return <div className="space-y-3">
    <p className="text-sm">{PRIVACY}</p>
    {!!value.local_media.images.length && <p className="rounded border border-line p-2 text-sm">Visual analysis requires a vision model configured in Settings. If none is connected, selected images are saved with the test but are not analyzed. Remove images you do not want to send.</p>}
    {value.notes.map(note => <p key={note} className="text-xs text-muted">{note}</p>)}
    {!!value.text && <label className="block text-sm">Extracted document text<textarea aria-label="Extracted document text" className="mt-1 min-h-40 w-full rounded border border-line bg-panel p-2" maxLength={60000} value={value.text} onChange={e => set({ ...value, text: e.target.value })} /></label>}
    {!!value.transcript && <label className="block text-sm">Transcript to send (editable)<textarea aria-label="Transcript to send" className="mt-1 min-h-40 w-full rounded border border-line bg-panel p-2" maxLength={120000} value={value.transcript} onChange={e => set({ ...value, transcript: e.target.value })} /></label>}
    {value.local_media.duration != null && <p className="text-xs">Duration: {value.local_media.duration.toFixed(2)} seconds</p>}
    <div className="grid grid-cols-2 gap-2">{value.local_media.images.map((im, i) => <figure key={`${im.order}-${im.time}`} className="space-y-1"><img src={im.data} alt={im.time == null ? `Slide ${i + 1}` : `Video frame at ${im.time.toFixed(2)} seconds`} className="max-h-40" /><figcaption className="text-xs">{im.time == null ? `Slide ${i + 1}` : `${im.time.toFixed(2)}s`} <button type="button" className="text-brand" onClick={() => set({ ...value, local_media: { ...value.local_media, images: value.local_media.images.filter((_, k) => i !== k) } })}>Remove image</button></figcaption></figure>)}</div>
  </div>;
}
