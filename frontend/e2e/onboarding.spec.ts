import { test, expect } from "@playwright/test";

test("a new account is guided from sign-up to a first test", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/register");
  await page.getByLabel("Email").fill(`new-${info.project.name}-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("a-new-beta-password");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).not.toHaveURL(/register/);

  const guide = page.getByRole("region", { name: "Welcome to the Kruvim beta" });
  await expect(guide).toBeVisible();
  await expect(guide.getByText("No model connected yet")).toBeVisible();
  await expect(guide.getByRole("link", { name: "Add a model key" })).toHaveAttribute("href", "/settings?tab=model-keys");

  await guide.getByRole("button", { name: "fill in an example" }).click();
  await expect(page.getByLabel(/Transcript, subtitles or script/)).toHaveValue(/Consistency beats intensity/);
  await page.getByRole("button", { name: "Test it", exact: true }).click();
  await expect(page).toHaveURL(/simulations\//);

  await page.goto("/");
  await expect(guide.getByText("(done)")).toHaveCount(2);         // steps 1 and 3
  await guide.getByRole("button", { name: "Hide the getting started guide" }).click();
  await expect(guide).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Test something" })).toBeVisible();
  await expect(guide).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("a missing or deleted test explains itself instead of loading forever", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo@kruvim.local");
  await page.getByLabel("Password").fill("kruvim-demo-2026");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/login/);
  await page.goto("/simulations/00000000000000000000000000000000");
  await expect(page.getByRole("alert").getByText("Couldn't load this test")).toBeVisible();
  await expect(page.getByText("was not found")).toBeVisible();
  await page.getByRole("link", { name: "Back to my tests" }).click();
  await expect(page).toHaveURL(/\/tests$/);
});
