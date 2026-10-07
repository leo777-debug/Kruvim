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
assert.deepEqual(NAV_SECTIONS.map(({ label }) => label), ["", "Advanced"]);
assert.deepEqual(NAV_SECTIONS[0].items.map(({label}) => label), ["Home", "My tests", "My audience", "Data pool", "Settings", "Help"]);
assert.equal(NAV_SECTIONS[0].items.length, 6);
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
assert.deepEqual(readCollapsedSections("new-user", storage), {advanced: true});
writeCollapsedSections("creator-a", {advanced: false}, storage);
writeCollapsedSections("creator-b", {advanced: true}, storage);
assert.deepEqual(readCollapsedSections("creator-a", storage), {advanced: false});
assert.deepEqual(readCollapsedSections("creator-b", storage), {advanced: true});
assert.notEqual(sidebarPreferenceKey("creator-a"), sidebarPreferenceKey("creator-b"));
saved.set(sidebarPreferenceKey("bad"), "invalid");
assert.deepEqual(readCollapsedSections("bad", storage), {advanced: true});
const blocked = {getItem: () => {throw new Error("blocked")}, setItem: () => {throw new Error("blocked")}};
assert.deepEqual(readCollapsedSections("creator-a", blocked), {advanced: true});
assert.doesNotThrow(() => writeCollapsedSections("creator-a", {advanced: false}, blocked));
console.log(`Navigation: ${links.length} real routes, six default items, admin visibility and per-user advanced preferences passed.`);
