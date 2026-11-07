import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";

const root = new URL("../dist/", import.meta.url);
const manifest = JSON.parse(readFileSync(new URL(".vite/manifest.json", root), "utf8"));

function dependencies(entry, seen = new Set()) {
  if (seen.has(entry)) return seen;
  seen.add(entry);
  for (const key of manifest[entry].imports ?? []) dependencies(key, seen);
  return seen;
}

// Include every static dependency, but not code requested by later interactions.
// The previous entry required 1,025,927 raw / 307,695 gzip bytes.
for (const entry of ["index.html", "src/features/simulations/NewSimulationPage.tsx", "src/features/projects/ProjectsPage.tsx"]) {
  const files = [...dependencies(entry)].map(key => manifest[key].file);
  const gzipBytes = files.reduce((sum, file) => sum + gzipSync(readFileSync(new URL(file, root))).length, 0);
  assert.ok(gzipBytes < 190_000, `${entry} requires ${gzipBytes} gzip bytes; keep charts, graph and Markdown out of basic pages`);
  console.log(`${entry}: ${gzipBytes.toLocaleString()} gzip bytes across ${files.length} chunks`);
}

const project = [...dependencies("src/features/projects/ProjectPage.tsx")];
assert.ok(!project.includes("src/features/simulations/SimulationPage.tsx"), "Project tables must not load the full simulation page");
console.log("Page loading bundle budgets passed.");
