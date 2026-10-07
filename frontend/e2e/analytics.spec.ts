import {test, expect, type Page} from "@playwright/test";
import path from "node:path";

async function choose(page: Page, field: string, option: string) {
  await page.getByRole("combobox", {name: field, exact: true}).click();
  await page.getByRole("option", {name: option, exact: true}).click();
}

test("analytics preview, reusable mapping, audience fill and deletion", async ({page}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (r) => {if (r.url().includes("/api/v1/") && r.status() >= 400) errors.push(`${r.status()} ${r.url()}`);});
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo@kruvim.local");
  await page.getByLabel("Password").fill("kruvim-demo-2026");
  await page.getByRole("button", {name: "Sign in", exact: true}).click();
  await expect(page).not.toHaveURL(/login/);
  await page.goto("/my-audience");
  await page.getByLabel("Analytics file").setInputFiles(path.resolve("../backend/tests/fixtures/analytics/posts.csv"));
  await page.getByRole("switch", {name: /This is my own aggregate analytics/}).click();
  await page.getByRole("button", {name: "Preview file", exact: true}).click();
  await expect(page.getByRole("button", {name: "Preview mapped data", exact: true})).toBeVisible();
  await choose(page, "Post date", "Date");
  await choose(page, "caption", "Title");
  await choose(page, "views", "Views");
  await page.getByLabel("Save this mapping as").fill("Browser fixture mapping");
  await page.getByRole("button", {name: "Preview mapped data", exact: true}).click();
  await expect(page.getByText("3 rows ready. Missing columns stay unavailable.")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
  await page.getByRole("button", {name: "Import mapped data", exact: true}).click();
  await expect(page.getByText(/views: 200/)).toBeVisible();
  await choose(page, "Data to import", "Follower breakdown");
  await page.getByLabel("Analytics file").setInputFiles(path.resolve("../backend/tests/fixtures/analytics/audience.csv"));
  await page.getByRole("button", {name: "Preview file", exact: true}).click();
  await choose(page, "category", "Category");
  await choose(page, "value", "Percentage");
  await choose(page, "dimension", "Dimension");
  const categoryMap = page.getByLabel("Category labels (optional JSON mapping)");
  await categoryMap.fill('{"United Arab Emirates":"AE","Saudi Arabia":"SA"}');
  await categoryMap.blur();
  await page.getByRole("button", {name: "Preview mapped data", exact: true}).click();
  await page.getByRole("button", {name: "Import mapped data", exact: true}).click();
  await expect(page.getByText(/Current: My imported audience/)).toBeVisible();
  await expect(page.getByText(/18:00: 60%/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", {name: "Delete imported data", exact: true}).click();
  await expect(page.getByText("Import post performance to calculate your own medians.")).toBeVisible();
  expect(errors).toEqual([]);
});
