import { test, expect } from "@playwright/test";

test("billing shows the paid plan and blocks unpaid simulation work", async ({ page }) => {
  test.skip(process.env.KRUVIM_VERIFY_BILLING !== "true", "Run with KRUVIM_VERIFY_BILLING=true for the isolated paywall server.");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo@kruvim.local");
  await page.getByLabel("Password").fill("kruvim-demo-2026");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/login/);
  await page.goto("/usage");
  await expect(page.getByRole("heading", { name: "Billing and credits", exact: true })).toBeVisible();
  await expect(page.getByText("AED 50", { exact: true })).toBeVisible();
  await expect(page.getByText("AED 20 one-time top-up", { exact: true })).toBeVisible();
  await expect(page.getByText(/Includes AED 10 of AI usage per seat/)).toBeVisible();
  await expect(page.getByText(/Adds AED 10 of AI usage to your seat/)).toBeVisible();
  await expect(page.getByText("AED 0.00 remaining", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Subscribe", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Top up AI usage", exact: true })).toBeDisabled();
  await expect(page.getByText("Payments are being set up", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  await page.screenshot({ path: test.info().outputPath("billing.png"), fullPage: true });
  const login = await page.request.post("/api/v1/auth/login", { data: {
    email: "demo@kruvim.local", password: "kruvim-demo-2026",
  } });
  const session = await login.json();
  const headers = { Authorization: `Bearer ${session.access_token}`, "X-Org-Id": session.orgs[0].id };
  const projects = await (await page.request.get("/api/v1/projects", { headers })).json();
  const project = Array.isArray(projects) ? projects[0] : projects.items[0];
  const denied = await page.request.post(`/api/v1/projects/${project.id}/simulations`, { headers, data: {} });
  expect(denied.status()).toBe(402);
  expect((await denied.json()).error.code).toBe("subscription_required");
  await page.goto("/usage?checkout=returned");
  await expect(page.getByText("Checking payment status", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Subscribe", exact: true })).toBeDisabled();
  expect(errors).toEqual([]);
});
