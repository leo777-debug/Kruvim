import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const text = readFileSync(new URL("../src/features/simulations/agentSelection.ts", import.meta.url), "utf8");
const code = ts.transpileModule(text, { compilerOptions: { module: ts.ModuleKind.ES2022 } }).outputText;
const { selectedAgent } = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
assert.equal(selectedAgent(["p:riyadh", "p:dubai"], null), "p:riyadh");
assert.equal(selectedAgent(["p:riyadh", "p:dubai"], "p:dubai"), "p:dubai");
assert.equal(selectedAgent(["p:riyadh"], "p:dubai"), "p:riyadh");
assert.equal(selectedAgent([], "p:dubai"), null);
assert.equal(selectedAgent(["p:riyadh"], "missing"), "p:riyadh");
console.log("Agent selection: initial, retained, filtered, empty and invalid-link cases passed.");
