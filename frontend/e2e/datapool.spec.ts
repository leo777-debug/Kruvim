import { test, expect } from "@playwright/test";

async function signIn(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo@kruvim.local");
  await page.getByLabel("Password").fill("kruvim-demo-2026");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/login/);
}

test("all Data pool tabs settle and World Monitor upstreams are visible", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await signIn(page);
  await page.goto("/data-pool");
  await expect(page.getByRole("heading", { name: "World Monitor public feeds" })).toBeVisible();
  await expect(page.getByText("Dubai", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Signals", exact: true }).click();
  await expect(page.getByLabel("Region", { exact: true })).toBeVisible();
  await expect(page.getByText("Loading signals…", { exact: true })).not.toBeVisible();
  await page.getByRole("button", { name: "Connectors", exact: true }).click();
  await expect(page.getByRole("cell", { name: /GDELT free news events/ }).first()).toBeVisible();
  await page.getByRole("button", { name: "Social listening", exact: true }).click();
  await expect(page.getByLabel("Topic", { exact: true })).toBeVisible();
  const uae = page.getByRole("checkbox", { name: "UAE", exact: true });
  await expect(uae).toHaveAttribute("aria-checked", "true");
  await uae.click();
  await expect(uae).toHaveAttribute("aria-checked", "false");
  await page.getByRole("button", { name: "Survey data", exact: true }).click();
  await expect(page.getByText("Population versions", { exact: true })).toBeVisible();
  await expect(page.getByText("Loading datasets…", { exact: true })).not.toBeVisible();
  await page.getByRole("button", { name: "Sources", exact: true }).click();
  await expect(page.getByLabel("Search sources", { exact: true })).toBeVisible();
  await expect(page.getByText("Loading sources…", { exact: true })).not.toBeVisible();
  await expect(page.getByText("GDELT free news events", { exact: true }).last()).toBeVisible();
  expect(errors).toEqual([]);
});

test("Data pool failures show a working retry instead of an endless loader", async ({ page }) => {
  await signIn(page);
  let fail = true;
  await page.route("**/api/v1/datapool/world", route => fail
    ? route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { message: "Temporary upstream problem" } }) })
    : route.continue());
  await page.goto("/data-pool");
  await expect(page.getByText("Regions could not load", { exact: true })).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  await expect(page.getByText("Dubai", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Regions could not load", { exact: true })).not.toBeVisible();
});
