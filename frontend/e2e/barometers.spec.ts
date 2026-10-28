import { test, expect } from "@playwright/test";

test("a messy barometer file is added with its source, indexed verbatim and searchable", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo@kruvim.local");
  await page.getByLabel("Password").fill("kruvim-demo-2026");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/login/);

  await page.goto("/barometers");
  await expect(page.getByRole("heading", { name: "Barometers" })).toBeVisible();
  const title = `Baromètre ${info.project.name}`;
  const csv = `Enquête ${info.project.name};;\nRégion;Chômage %\n  Occitanie ; 9,4 (prov.)\n* révisé\n`;
  await page.getByLabel("File").setInputFiles({ name: `barometre-${info.project.name}.csv`, mimeType: "text/csv", buffer: Buffer.from(csv, "utf-8") });
  await page.getByLabel("Country").fill("FR");
  await page.getByLabel("Publisher").fill("INSEE");
  await page.getByLabel("Title").fill(title);
  await page.getByRole("button", { name: "Add to library" }).click();
  const row = page.getByRole("row").filter({ hasText: title });
  await expect(row.getByText(/passages?$/)).toBeVisible();

  await page.getByLabel("Search barometer passages").fill("chômage Occitanie");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.locator("pre").filter({ hasText: "  Occitanie ; 9,4 (prov.)" }).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
  expect(errors).toEqual([]);
});
