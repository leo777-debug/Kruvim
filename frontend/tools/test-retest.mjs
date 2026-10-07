import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/features/simulations/retest.ts", import.meta.url), "utf8");
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022 } }).outputText;
const { prepareRetest } = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
const sim = {
  content: { type: "video", transcript: "Old hook. The rest.", variant_b: { transcript: "Other version" } },
  card: { segments: [{ text: "Old hook." }] },
  results: { recommendations: [{ id: "hook" }], rewrites: { hook: { text: "New hook." } } },
};
assert.deepEqual(prepareRetest(sim), { automatic: true, content: { ...sim.content, transcript: "New hook. The rest.", variant_b: null } });
assert.equal(sim.content.transcript, "Old hook. The rest.");
assert.equal(sim.content.variant_b.transcript, "Other version");
const endingFix = { ...sim, results: { ...sim.results, recommendations: [{ id: "trim" }] } };
assert.deepEqual(prepareRetest(endingFix), { automatic: false, content: { ...sim.content, variant_b: null } });
for (const extra of [{ asset_id: "upload" }, { asset_ids: ["upload"] }, { transcript: "" }]) {
  assert.equal(prepareRetest({ ...sim, content: { ...sim.content, ...extra } }).automatic, false);
}
const text = prepareRetest({ ...sim, content: { type: "text", text: "Old hook. The rest." } });
assert.equal(text.content.text, "New hook. The rest.");
const oldAB = prepareRetest({ ...sim, content: { ...sim.content, card_b: { summary: "Old B card" }, b_kind: "version" } });
assert.equal(oldAB.content.card_b, undefined);
assert.equal(oldAB.content.b_kind, undefined);
assert.equal(oldAB.content.variant_b, null);
assert.equal(prepareRetest({ ...sim, results: {} }).automatic, false);
console.log("Re-test: primary content, correct fix, uploaded media, empty script and original isolation passed.");
