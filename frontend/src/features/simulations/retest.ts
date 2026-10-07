import type { Simulation } from "@/lib/types";

export function prepareRetest(sim: Simulation) {
  const field = sim.content.type === "text" ? "text" : "transcript";
  const hook = sim.results?.rewrites?.hook?.text;
  const first = sim.card?.segments?.[0]?.text;
  const original = String(sim.content[field] || "");
  const automatic = !!(sim.results?.recommendations?.[0]?.id === "hook" && hook && original &&
    !sim.content.asset_id && !sim.content.asset_ids?.length);
  const changes = automatic ? { [field]: first && original.includes(first) ? original.replace(first, hook) : `${hook} ${original}` } : {};
  const content: Simulation["content"] = { ...sim.content, ...changes, variant_b: null };
  delete content.card_b;
  delete content.b_kind;
  return { automatic, content };
}
