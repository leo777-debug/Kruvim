import { test, expect } from "@playwright/test";

test("private uploads stay private while public contributions are readable across workspaces", async ({ page, browser }) => {
  const suffix = `${test.info().project.name}-${Date.now()}`;
  const password = "library-test-password-2026";
  const email = `library-owner-${suffix}@example.com`;
  const readerEmail = `library-reader-${suffix}@example.com`;
  const publicName = `Community coffee research ${suffix}`;
  for (const account of [email, readerEmail]) {
    const response = await page.request.post("http://127.0.0.1:8016/api/v1/auth/register", {
      data: { email: account, password, org_name: account.split("@")[0] },
    });
    expect(response.status()).toBe(200);
  }
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  async function signIn(target: typeof page, account: string) {
    await target.goto("/login");
    await target.getByLabel("Email", { exact: true }).fill(account);
    await target.getByLabel("Password", { exact: true }).fill(password);
    await target.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(target).not.toHaveURL(/login/);
  }
  await signIn(page, email);
  await page.goto("/data-pool");
  await expect(page).toHaveURL(/data-library$/);
  await expect(page.getByRole("link", { name: "Data pool", exact: true })).toHaveCount(0);
  await expect(page.getByText("Your private library is empty.", { exact: false })).toBeVisible();
  await page.getByLabel("New folder name").fill("Confidential customer research");
  await page.getByLabel("Use for", { exact: true }).selectOption("shared");
  await page.getByRole("button", { name: "Create folder", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("Private coffee finding");
  await page.getByLabel("Data / observation", { exact: true }).fill("Private workspace-only observation.");
  await page.getByRole("button", { name: "Save row", exact: true }).click();
  await expect(page.getByRole("cell", { name: "Private coffee finding", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Public", exact: true }).click();
  await page.getByLabel("New folder name").fill(publicName);
  await expect(page.getByRole("button", { name: "Create folder", exact: true })).toBeDisabled();
  await page.getByRole("checkbox", { name: /I understand that all data/ }).check();
  await page.getByRole("button", { name: "Create folder", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("Public coffee finding");
  await page.getByLabel("Data / observation", { exact: true }).fill("Example community contribution, voluntarily shared.");
  await page.getByRole("button", { name: "Save row", exact: true }).click();
  await expect(page.getByRole("cell", { name: "Public coffee finding", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  await page.screenshot({ path: test.info().outputPath("public-library-owner.png"), fullPage: true });

  const readerContext = await browser.newContext({ baseURL: "http://127.0.0.1:5186", viewport: page.viewportSize()! });
  const reader = await readerContext.newPage();
  try {
    await signIn(reader, readerEmail);
    await reader.goto("/data-library");
    await expect(reader.getByText("Your private library is empty.", { exact: false })).toBeVisible();
    await reader.getByRole("button", { name: "Public", exact: true }).click();
    await reader.getByRole("button", { name: new RegExp(publicName) }).click();
    await expect(reader.getByRole("cell", { name: "Public coffee finding", exact: true })).toBeVisible();
    await expect(reader.getByRole("button", { name: "Edit", exact: true })).toHaveCount(0);
    await expect(reader.getByRole("button", { name: "Delete", exact: true })).toHaveCount(0);
    await expect(reader.getByText("Private coffee finding", { exact: true })).toHaveCount(0);
    await expect(reader.getByRole("link", { name: /Open Supabase/ })).toHaveCount(0);
    await reader.screenshot({ path: test.info().outputPath("public-library-reader.png"), fullPage: true });
  } finally { await readerContext.close(); }
  await page.goto("/");
  const mode = page.getByRole("combobox", { name: "Library mode", exact: true });
  await expect(mode).toContainText("Private");
  await mode.click();
  await page.getByRole("option", { name: "Public — also include community contributions", exact: true }).click();
  await expect(mode).toContainText("Public");
  expect(errors).toEqual([]);
});
