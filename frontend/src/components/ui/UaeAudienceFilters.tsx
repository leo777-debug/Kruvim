import { CheckRow, Field, Switch } from "@/components/ui/primitives";
import { useReference } from "@/lib/queries";

export function UaeAudienceFilters({ value, onChange }: { value: Record<string, any>; onChange: (v: any) => void }) {
  const ref = useReference();
  const groups = [["emirates", "residence_emirate", "Residence emirate"], ["nationality_groups", "nationality_group", "Nationality group"], ["income_bands", "income_band", "Income / occupation band"], ["languages", "language", "Language"]];
  return <div className="space-y-3"><p className="text-xs text-muted">UAE attributes are simulated estimates until approved tables are imported. AE includes every emirate. Selecting these filters narrows the audience to UAE agents.</p>
    <div className="grid gap-3 sm:grid-cols-2">{groups.map(([key, dimension, label]) => <Field key={key} label={label} hint={(value[key] || []).length ? `${value[key].length} selected` : "Any"}><div className="max-h-36 overflow-y-auto rounded border border-line p-1">{(ref.data?.uae_dimensions?.[dimension] || []).map((v) => <CheckRow key={v} label={v} checked={(value[key] || []).includes(v)} onChange={() => onChange({ ...value, [key]: (value[key] || []).includes(v) ? value[key].filter((x: string) => x !== v) : [...(value[key] || []), v] })} />)}</div></Field>)}</div>
    <Switch checked={!!value.include_visitors} onChange={(v) => onChange({ ...value, include_visitors: v })} label="Include optional visitor layer" />
    {value.include_visitors && <p className="text-xs text-muted">Visitors require separately sourced origin and flow data. Without an imported visitor layer, no visitor counts are invented.</p>}
  </div>;
}
