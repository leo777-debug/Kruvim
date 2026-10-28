import AxeBuilder from "@axe-core/playwright";
import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import fs from "node:fs";

/** Every screen, signed in and out, with real data: WCAG 2.1 A/AA checks (serious and critical issues fail the test),
 * no sideways scrolling, no script errors. KRUVIM_TOUR=1 also saves a screenshot of each screen for design review. */
const API = "http://127.0.0.1:8016/api/v1";

async function token(request: APIRequestContext) {
  const r = await request.post(`${API}/auth/login`, { data: { email: "demo@kruvim.local", password: "kruvim-demo-2026" } });
  return { Authorization: `Bearer ${(await r.json()).access_token}` };
}

async function completedSimulation(request: APIRequestContext) {
  const h = await token(request);
  const projects = await (await request.get(`${API}/projects`, { headers: h })).json();
  const existing = await (await request.get(`${API}/simulations`, { headers: h })).json();
  const done = (existing.items || existing).find?.((s: any) => s.status === "completed" && s.report_status === "done");
  if (done) return { sim: done.id, project: projects[0].id, h };
  const body = { name: "Accessibility tour", requirement: "How will young Gulf professionals react to this routine?",
    content: { type: "video", title: "Apartment workout", platform: "tiktok", transcript: "Three minutes, no equipment. Squats, plank, done. Consistency beats intensity. Follow for part two." },
    audience: { regions: ["AE"] }, overrides: { voice: 10, crowd: 500, stakeholders: 1, hours: 2, minutes_per_round: 60, listening: false } };
  const sim = await (await request.post(`${API}/projects/${projects[0].id}/simulations`, { headers: h, data: body })).json();
  const wait = async (field: string, want: string) => {
    for (let i = 0; i < 240; i++) {
      const s = await (await request.get(`${API}/simulations/${sim.id}`, { headers: h })).json();
      if (s[field] === want) return;
      if (s.status === "failed") throw new Error(s.error);
      await new Promise((r) => setTimeout(r, 500));
    }
    throw new Error(`timed out waiting for ${field}=${want}`);
  };
  await request.post(`${API}/simulations/${sim.id}/graph`, { headers: h }); await wait("status", "graph_ready");
  await request.post(`${API}/simulations/${sim.id}/environment`, { headers: h }); await wait("status", "ready");
  await request.post(`${API}/simulations/${sim.id}/start`, { headers: h }); await wait("report_status", "done");
  return { sim: sim.id, project: projects[0].id, h };
}

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
  for (const [name, url] of [["login", "/login"], ["register", "/register"], ["shared-results", new URL(share.url).pathname]] as const) {
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
    ["calibration", "/calibration"], ["accuracy", "/accuracy"], ["usage", "/usage"], ["admin", "/admin"],
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
