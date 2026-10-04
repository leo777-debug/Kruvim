import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { matchPath } from "react-router-dom";
import ts from "typescript";

const source = readFileSync(new URL("../src/components/layout/navigation.ts", import.meta.url), "utf8");
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022 } }).outputText;
const { NAV_SECTIONS, visibleSections, isNavActive, sidebarPreferenceKey, readCollapsedSections, writeCollapsedSections } =
  await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);

// Read the actual JSX Route declarations, ignoring the catch-all: a broken link
// must fail even though the application would otherwise redirect it to Overview.
const app = ts.createSourceFile("App.tsx", readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const paths = new Set();
function attribute(tag, name) {
  return tag.attributes.properties.find((attr) => ts.isJsxAttribute(attr) && attr.name.text === name);
}
function visit(node, parent = "/") {
  if ((ts.isJsxElement(node) && node.openingElement.tagName.getText(app) === "Route") ||
      (ts.isJsxSelfClosingElement(node) && node.tagName.getText(app) === "Route")) {
    const tag = ts.isJsxElement(node) ? node.openingElement : node;
    const path = attribute(tag, "path")?.initializer;
    const value = path && ts.isStringLiteral(path) ? path.text : "";
    if (value === "*") return;
    const absolute = value.startsWith("/") ? value : `${parent === "/" ? "" : parent}/${value}`;
    const resolved = absolute.replace(/\/$/, "") || "/";
    if (attribute(tag, "element") && (value || attribute(tag, "index"))) paths.add(resolved);
    if (ts.isJsxElement(node)) node.children.forEach((child) => visit(child, resolved));
    return;
  }
  ts.forEachChild(node, (child) => visit(child, parent));
}
visit(app);

const links = NAV_SECTIONS.flatMap((section) => section.items);
assert.deepEqual(NAV_SECTIONS.map(({ label }) => label), ["Create", "Audience", "Intelligence", "Accuracy", "Workspace"]);
assert.deepEqual(NAV_SECTIONS.map(({ items }) => items.map(({ label }) => label)), [
  ["Overview", "Projects", "All runs"], ["My audience", "Saved audiences", "Population"],
  ["Data pool", "Monitoring"], ["Calibration", "Public accuracy"], ["Settings", "Usage and credits", "Platform admin"],
]);
assert.equal(new Set(links.map(({ to }) => to)).size, links.length);
for (const item of links) {
  assert.ok(paths.has(item.to), `${item.label} links to an undeclared route: ${item.to}`);
  assert.ok(item.description.startsWith(item.label + ":") && !item.description.includes("\n"));
  assert.equal(links.filter((link) => isNavActive(link, item.to)).length, 1, `Exactly one item must be active at ${item.to}`);
  assert.equal(isNavActive(item, item.to), !!matchPath({ path: item.to, end: item.end ?? false }, item.to));
  for (const pathname of [item.to.toUpperCase(), item.to + "/", "/projects/project-id/new", "/projects-old"]) {
    assert.equal(isNavActive(item, pathname), !!matchPath({ path: item.to, end: item.end ?? false }, pathname));
  }
}
assert.ok(paths.has("/audiences") && paths.has("/saved-audiences"), "Keep the legacy audience route");
assert.equal(isNavActive(links.find((item) => item.to === "/projects"), "/projects/project-id/new"), true);
assert.equal(isNavActive(links.find((item) => item.to === "/projects"), "/projects-old"), false);
assert.equal(visibleSections(false).flatMap(({ items }) => items).some(({ to }) => to === "/admin"), false);
assert.equal(visibleSections(true).flatMap(({ items }) => items).some(({ to }) => to === "/admin"), true);

const saved = new Map();
const storage = { getItem: (key) => saved.get(key) ?? null, setItem: (key, value) => saved.set(key, value) };
writeCollapsedSections("creator-a", { create: true, audience: false }, storage);
writeCollapsedSections("creator-b", { workspace: true }, storage);
assert.deepEqual(readCollapsedSections("creator-a", storage), { create: true });
assert.deepEqual(readCollapsedSections("creator-b", storage), { workspace: true });
assert.notEqual(sidebarPreferenceKey("creator-a"), sidebarPreferenceKey("creator-b"));
assert.deepEqual(readCollapsedSections(undefined, storage), {});
storage.setItem(sidebarPreferenceKey("invalid"), "{broken");
assert.deepEqual(readCollapsedSections("invalid", storage), {});
storage.setItem(sidebarPreferenceKey("unknown"), JSON.stringify({ version: 1, collapsed: { create: true, accuracy: "true", alien: true } }));
assert.deepEqual(readCollapsedSections("unknown", storage), { create: true });
storage.setItem(sidebarPreferenceKey("future"), JSON.stringify({ version: 2, collapsed: { create: true } }));
assert.deepEqual(readCollapsedSections("future", storage), {});
const blocked = { getItem: () => { throw new Error("Storage denied"); }, setItem: () => { throw new Error("Storage denied"); } };
assert.deepEqual(readCollapsedSections("creator-a", blocked), {});
assert.doesNotThrow(() => writeCollapsedSections("creator-a", { audience: true }, blocked));
console.log(`Navigation: all ${links.length} links resolve to declared routes; grouping, active states, admin visibility and user-scoped preferences passed.`);
