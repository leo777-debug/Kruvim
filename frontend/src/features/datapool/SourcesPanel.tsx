import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, Select } from "@/components/ui/overlay";
import { Callout, Card, Empty, Field, Input, Status, Switch } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt } from "@/lib/utils";

export function SourcesPanel() {
  const admin = useAuth((s) => !!s.user?.is_superuser);
  const q = useQuery({ queryKey: ["sources"], queryFn: () => api<any[]>("/datapool/sources") });
  const [filter, setFilter] = useState("");
  const [pending, setPending] = useState(false);
  const [edit, setEdit] = useState<any>(null);
  const [draft, setDraft] = useState<any>({});
  const [configText, setConfigText] = useState("{}");
  let configValid = false;
  try { const config = JSON.parse(configText); configValid = !!config && !Array.isArray(config) && typeof config === "object"; } catch { /* Inline validation. */ }
  const save = useMutation({ mutationFn: () => api(`/datapool/sources/${edit.id}`, { method: "PATCH", json: draft }),
    onSuccess: () => { setEdit(null); q.refetch(); toast.success("Source updated"); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not update source") });
  const fetch = useMutation({ mutationFn: (id: string) => api(`/datapool/sources/${id}/fetch`, { method: "POST" }),
    onSuccess: (r) => { q.refetch(); toast.success(`${r.observations} observations imported; ${r.missing_cells} missing cells left empty`); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not import source") });
  const rows = (q.data || []).filter((r) => (!pending || r.status === "pending_import" || !r.observations || !r.production_eligible)
    && `${r.name} ${r.publisher} ${r.country} ${r.attributes.join(" ")}`.toLowerCase().includes(filter.toLowerCase()));
  return <div className="space-y-4">
    <Callout tone="info" title="Public sources, with their limitations">Figures retain the publisher's period and geography. No missing cells are filled. Sources awaiting commercial reuse approval contribute no production weight. Synthetic priors are labelled “estimate, source pending”.</Callout>
    <div className="flex flex-wrap items-center gap-4"><Input className="max-w-md" aria-label="Search sources" placeholder="Search publisher or attribute…" value={filter} onChange={(e) => setFilter(e.target.value)} />
      <label className="flex items-center gap-2 text-sm"><Switch checked={pending} onChange={setPending} />Pending import checklist</label></div>
    {q.isError && <Callout tone="warn">Could not load the source registry.</Callout>}
    {q.isLoading ? <p className="text-muted">Loading sources…</p> : !rows.length ? <Empty title="No matching sources" /> : <div className="grid min-w-0 gap-4 lg:grid-cols-2">{rows.map((r) => <Card key={r.id} className="min-w-0 space-y-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><a href={r.url} target="_blank" rel="noreferrer" className="font-medium text-brand hover:underline">{r.name}</a><Status tone={r.production_eligible ? "pos" : "warn"}>{r.status.replaceAll("_", " ")}</Status></div>
      <p className="text-xs text-muted">{r.publisher} · {r.country} · {r.geography_level} · {r.access_method.replaceAll("_", " ")} · {r.cadence}</p>
      <p className="break-words text-sm">{r.licence}</p>
      <p className="text-xs text-muted">{r.production_eligible ? "Approved for production weighting" : "Excluded from production weighting"} · Reliability weight: {r.reliability} · {r.observations} stored observations</p>
      <p className="text-xs text-muted">Last import: {r.last_imported_at ? fmt.date(r.last_imported_at) : "Pending"} · Terms checked: {fmt.day(r.last_checked_at)}</p>
      <p className="text-xs"><span className="text-muted">Feeds: </span>{r.attributes.join(", ").replaceAll("_", " ")}</p>
      <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-muted">{r.notes}</p>
      <p className="text-xs text-muted">Attribution: {r.attribution}</p>
      <div className="flex flex-wrap gap-2">{r.terms_url && <a className="text-xs text-brand hover:underline" href={r.terms_url} target="_blank" rel="noreferrer">Publisher terms</a>}
        {admin && <Button size="sm" onClick={() => { setEdit(r); setConfigText(JSON.stringify(r.config || {}, null, 2)); setDraft({ reliability: r.reliability, status: r.status, licence: r.licence, notes: r.notes, config: r.config || {}, licence_approved: r.licence_approved, approval_note: "" }); }}>Edit source</Button>}
        {admin && r.config?.endpoint && ["table", "sdmx", "world_bank"].includes(r.config?.adapter) && <Button size="sm" loading={fetch.isPending && fetch.variables === r.id} onClick={() => fetch.mutate(r.id)}>Import public feed</Button>}
      </div>
    </Card>)}</div>}
    <Dialog open={!!edit} onOpenChange={(v) => !v && setEdit(null)} title={`Edit ${edit?.name || "source"}`} footer={<><Button onClick={() => setEdit(null)}>Cancel</Button><Button variant="primary" disabled={!configValid} loading={save.isPending} onClick={() => save.mutate()}>Save source</Button></>}>
      <div className="space-y-3"><Field label="Reliability weight (0–1)"><Input type="number" min="0" max="1" step="0.05" value={draft.reliability ?? 0} onChange={(e) => setDraft({ ...draft, reliability: Number(e.target.value) })} /></Field>
        <Field label="Licence"><Input value={draft.licence || ""} onChange={(e) => setDraft({ ...draft, licence: e.target.value })} /></Field>
        <Field label="Notes and import instructions"><textarea aria-label="Notes and import instructions" className="min-h-28 w-full rounded border border-line bg-canvas p-2 text-sm" value={draft.notes || ""} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} /></Field>
        <Field label="Adapter and native-code mapping" help="Platform admin JSON: public feed URL, language and population_dimension_map. Changing configuration requires renewed reuse approval."><textarea aria-label="Adapter and native-code mapping" aria-invalid={!configValid} className="mono min-h-24 w-full rounded border border-line bg-canvas p-2 text-xs" value={configText} onChange={(e) => { setConfigText(e.target.value); try { setDraft({ ...draft, config: JSON.parse(e.target.value) }); } catch { /* Saving is disabled until valid. */ } }} /></Field>
        <label className="flex items-center gap-2 text-sm"><Switch checked={draft.status === "active"} onChange={(v) => setDraft({ ...draft, status: v ? "active" : "pending_import" })} />Activate source</label>
        <label className="flex items-center gap-2 text-sm"><Switch checked={!!draft.licence_approved} onChange={(v) => setDraft({ ...draft, licence_approved: v })} />Commercial reuse approved</label>
        {draft.licence_approved && <Field label="Approval evidence" help="Required: cite the resource licence or publisher permission that permits commercial reuse."><Input value={draft.approval_note || ""} onChange={(e) => setDraft({ ...draft, approval_note: e.target.value })} /></Field>}
      </div>
    </Dialog>
  </div>;
}

export function ObservationMappingDialog({ d, onClose }: { d: any; onClose: () => void }) {
  const cols: string[] = d.columns;
  const [mapping, setMapping] = useState<any>(d.mapping?.value_col ? d.mapping : { metric: "", unit: "", geography: "", value_col: "", period_col: "", period_format: "date", dimensions: {} });
  const [summary, setSummary] = useState<any>(d.summary?.native_grain ? d.summary : null);
  const [dimensionText, setDimensionText] = useState(JSON.stringify(mapping.dimensions));
  let dimensionValid = false;
  try { const v = JSON.parse(dimensionText); dimensionValid = !!v && !Array.isArray(v) && typeof v === "object" && Object.values(v).every((x) => typeof x === "string"); } catch { /* Show invalid input and keep preview disabled. */ }
  const run = useMutation({ mutationFn: () => api(`/datapool/datasets/${d.id}/mapping`, { method: "PUT", json: mapping }), onSuccess: (r) => setSummary(r.summary), onError: (e) => toast.error(e instanceof ApiError ? e.message : "Mapping failed") });
  const pick = (key: string, label: string) => <Field label={label}><Select value={mapping[key] || "-"} onChange={(v) => setMapping({ ...mapping, [key]: v === "-" ? "" : v })} options={[{ value: "-", label: "Choose column" }, ...cols.map((c) => ({ value: c, label: c }))]} /></Field>;
  return <Dialog open wide title={`Map source observations: ${d.name}`} onOpenChange={(v) => !v && onClose()} description="Map native figures, never respondent rows or interpolated values. Original file is retained. Missing figure cells are skipped and reported." footer={<><Button onClick={onClose}>Close</Button><Button variant="primary" disabled={!dimensionValid} loading={run.isPending} onClick={() => run.mutate()}>Preview observations</Button></>}>
    <div className="grid gap-3 sm:grid-cols-2">{pick("value_col", "Numeric value column")}{pick("period_col", "Native period column")}
      {["metric", "unit", "geography"].map((k) => <Field key={k} label={k[0].toUpperCase() + k.slice(1)} hint="Fixed value, or use a mapped column below"><Input value={mapping[k] || ""} onChange={(e) => setMapping({ ...mapping, [k]: e.target.value })} /></Field>)}
      <Field label="Period format"><Select value={mapping.period_format} onChange={(v) => setMapping({ ...mapping, period_format: v })} options={["year", "month", "date"].map((v) => ({ value: v, label: v }))} /></Field>
      {pick("metric_col", "Metric column (optional)")}{pick("unit_col", "Unit column (optional)")}{pick("geography_col", "Geography column (optional)")}
      {pick("period_start_col", "Period start column (optional)")}{pick("period_end_col", "Period end column (optional)")}
    </div>
    <Field className="mt-4" label="Dimension mapping" help={'JSON keys to columns, e.g. {"emirate":"Emirate","sex":"Sex","age_band":"Age band"}. No absent dimensions are filled.'}><textarea aria-invalid={!dimensionValid} className="min-h-20 w-full rounded border border-line bg-canvas p-2 text-sm" value={dimensionText} onChange={(e) => { setDimensionText(e.target.value); setSummary(null); try { const dimensions = JSON.parse(e.target.value); setMapping({ ...mapping, dimensions }); } catch { /* Preview is disabled until valid. */ } }} /></Field>
    {summary && <div className="mt-4 space-y-2"><p className="text-sm">{summary.observations} native observations · {summary.missing_cells} missing cells skipped · {summary.geographies.join(", ")}</p><div className="overflow-x-auto"><table className="dt"><thead><tr><th>Metric</th><th>Dimensions</th><th>Value</th><th>Period</th></tr></thead><tbody>{summary.preview.map((o: any, i: number) => <tr key={i}><td>{o.metric}</td><td>{JSON.stringify(o.dimensions)}</td><td>{o.value} {o.unit}</td><td>{o.period_start} — {o.period_end}</td></tr>)}</tbody></table></div><p className="text-xs text-muted">Close the preview, then Apply to store the figures. Licence approval is a separate platform admin action.</p></div>}
  </Dialog>;
}
