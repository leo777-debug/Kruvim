import { test, expect } from "@playwright/test";

test("an admin adds, rejects and replaces a model key and sets spending limits", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo@kruvim.local");
  await page.getByLabel("Password").fill("kruvim-demo-2026");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/login/);

  await page.goto("/settings?tab=model-keys");
  const gemini = page.getByRole("listitem").filter({ hasText: "Google Gemini" });
  await gemini.getByRole("button", { name: /Add key|Replace/ }).click();
  await page.getByLabel("API key").fill("bad-AIzaWrongKey");
  await page.getByRole("button", { name: "Check and save" }).click();
  await expect(page.getByText("Google Gemini rejected this key", { exact: false })).toBeVisible();

  await page.getByLabel("API key").fill("AIzaGoodKey1234567890");
  await page.getByRole("button", { name: "Check and save" }).click();
  await expect(gemini.getByText("Working")).toBeVisible();
  await expect(gemini.getByText("AIz…7890")).toBeVisible();
  await expect(page.getByText("AIzaGoodKey1234567890")).toHaveCount(0);   // never shown back in full

  await page.goto("/settings?tab=limits");
  await page.getByLabel("Model calls per month").fill("5000");
  await page.getByLabel("Model calls per member per day").fill("400");
  await page.getByRole("button", { name: "Save limits" }).click();
  await expect(page.getByText("Spending limits saved")).toBeVisible();
  await page.goto("/usage");
  await expect(page.getByRole("progressbar", { name: "Model calls this month" })).toBeVisible();
  await expect(page.getByText("of 5,000")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
  expect(errors).toEqual([]);
});
