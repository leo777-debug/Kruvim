import AxeBuilder from "@axe-core/playwright";
import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";

/** Every screen, signed in and out, with real data: WCAG 2.1 A/AA checks (serious and critical issues fail the test),
 * no sideways scrolling, no script errors. KRUVIM_TOUR=1 also saves a screenshot of each screen for design review. */
import { API, completedSimulation, token } from "./helpers";

async function audit(page: Page, name: string, project: string) {
  // Not "networkidle": live screens keep an event stream open. Wait for content instead of loading placeholders.
  await page.waitForLoadState("load");
  await page.locator("main, form").first().waitFor();
  await page.waitForFunction(() => !document.querySelector(".animate-pulse, .animate-spin"), null, { timeout: 15_000 }).catch(() => {});
  await page.waitForTimeout(300);
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const issues = result.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length,
    targets: v.nodes.slice(0, 4).map((n) => n.target.join(" ")) }));
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  if (process.env.KRUVIM_TOUR) {
    fs.mkdirSync("test-results/tour", { recursive: true });
    await page.screenshot({ path: `test-results/tour/${project}-${name}.png`, fullPage: true });
  }
  return { name, issues, overflow };
}

test("every screen meets WCAG 2.1 AA basics and fits the screen", async ({ page, request }, info) => {
  test.setTimeout(600_000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const { sim, project } = await completedSimulation(request);
  const h = await token(request);
  const share = await (await request.post(`${API}/simulations/${sim}/shares`, { headers: h, data: { days: 1 } })).json();

  const report = [];
  for (const [name, url] of [["login", "/login"], ["register", "/register"], ["shared-results", new URL(share.url).pathname], ["public-record", "/record"]] as const) {
    await page.goto(url);
    report.push(await audit(page, name, info.project.name));
  }
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo@kruvim.local");
  await page.getByLabel("Password").fill("kruvim-demo-2026");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/login/);
  const screens: [string, string][] = [
    ["home", "/"], ["tests", "/tests"], ["my-audience", "/my-audience"], ["data-pool", "/data-pool"], ["barometers", "/barometers"],
    ["help", "/help"], ["overview", "/overview"], ["projects", "/projects"], ["project", `/projects/${project}`],
    ["new-test", `/projects/${project}/new`], ["simulation", `/simulations/${sim}`], ["runs", "/runs"],
    ["saved-audiences", "/saved-audiences"], ["population", "/population"], ["monitoring", "/monitoring"],
    ["calibration", "/calibration"], ["accuracy", "/accuracy"], ["track-record", "/track-record"], ["launches", "/launches"], ["usage", "/usage"], ["admin", "/admin"],
    ...["provider", "model-keys", "limits", "org", "members", "keys", "audit", "branding", "profile"].map((t) => [`settings-${t}`, `/settings?tab=${t}`] as [string, string]),
  ];
  for (const [name, url] of screens) {
    await page.goto(url);
    report.push(await audit(page, name, info.project.name));
  }
  fs.mkdirSync("test-results", { recursive: true });
  fs.writeFileSync(`test-results/accessibility-${info.project.name}.json`, JSON.stringify(report, null, 2));

  const blocking = report.flatMap((r) => r.issues.filter((i) => i.impact === "serious" || i.impact === "critical")
    .map((i) => `${r.name}: ${i.id} (${i.nodes}) ${i.help} -> ${i.targets.join(" | ")}`));
  const overflowing = report.filter((r) => r.overflow).map((r) => r.name);
  expect.soft(overflowing, "screens wider than the viewport").toEqual([]);
  expect.soft(blocking, "serious or critical accessibility issues").toEqual([]);
  expect(errors, "script errors").toEqual([]);
});
