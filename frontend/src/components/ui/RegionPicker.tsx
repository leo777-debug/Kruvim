import { useReference } from "@/lib/queries";
import { CheckRow } from "./primitives";

export function RegionPicker({ value, onChange }: { value: string[]; onChange: (value: string[]) => void }) {
  const ref = useReference();
  return <div className="grid gap-1 rounded-md border border-line p-2 sm:grid-cols-2">{ref.data?.regions.map((r) =>
    <CheckRow key={r.code} label={r.name} checked={value.includes(r.code)}
      onChange={(checked) => onChange(checked ? [...value, r.code] : value.filter((x) => x !== r.code))} />)}</div>;
}
