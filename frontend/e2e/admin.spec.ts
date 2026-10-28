import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "@playwright/test";

test("platform admin: every tab is accessible, invite links prefill sign-up, browser errors are reported", async ({ page }, info) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo@kruvim.local");
  await page.getByLabel("Password").fill("kruvim-demo-2026");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/login/);

  // A crash in the browser is reported to Kruvim's own error log.
  await page.evaluate((tag) => setTimeout(() => { throw new Error(`e2e deliberate crash ${tag}`); }), info.project.name);
  await page.waitForTimeout(500);

  await page.goto("/admin");
  for (const tab of ["Beta invites", "Users", "Usage", "Failed jobs", "Uploaded data", "Errors", "Organisations"]) {
    await page.getByRole("tab", { name: tab }).click();
    await page.waitForFunction(() => !document.querySelector(".animate-pulse, .animate-spin"), null, { timeout: 15_000 }).catch(() => {});
    const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    const serious = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${tab}: ${v.id}`);
    expect.soft(serious).toEqual([]);
    if (tab === "Errors") await expect(page.getByText(`e2e deliberate crash ${info.project.name}`).first()).toBeVisible();
  }

  await page.getByRole("tab", { name: "Beta invites" }).click();
  await page.getByRole("button", { name: "Create code" }).click();
  await page.getByLabel("Note").fill(`e2e cohort ${info.project.name}`);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  const link = await page.getByLabel("Sign-up link", { exact: true }).inputValue();
  const code = await page.getByLabel("Code", { exact: true }).inputValue();
  expect(code).toMatch(/^KRV-/);
  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByRole("row").filter({ hasText: `e2e cohort ${info.project.name}` }).getByText("active")).toBeVisible();

  await page.context().clearCookies();
  await page.evaluate(() => localStorage.clear());
  await page.goto(new URL(link).pathname + new URL(link).search);
  await expect(page.getByLabel("Invite code")).toHaveValue(code);
  await expect(page.getByRole("link", { name: "Terms of use" })).toBeVisible();

  for (const [path, title] of [["/privacy", "Privacy policy"], ["/terms", "Terms of use"]]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
    await expect(page.getByText("This document is a draft")).toBeVisible();
  }
});
