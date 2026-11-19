import { expect, test } from "@playwright/test";

test("forgot password submits and shows the same private confirmation", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("link", { name: "Forgot password?" }).click();
  await page.getByLabel("Email", { exact: true }).fill(`unknown-${Date.now()}@example.com`);
  const sent = page.waitForResponse("**/api/v1/auth/forgot-password");
  await page.getByRole("button", { name: "Send email", exact: true }).click();
  expect((await sent).status()).toBe(200);
  await expect(page.getByRole("status")).toContainText("If this account is eligible");
});

test("reset uses a fragment token and clears the old session", async ({ page }) => {
  const token = "test-token-" + "x".repeat(48);
  await page.route("**/api/v1/auth/reset-password", async (route) => {
    expect(route.request().postDataJSON()).toEqual({ token, new_password: "new-secure-password" });
    await route.fulfill({ json: { ok: true } });
  });
  await page.goto(`/reset-password#token=${token}`);
  await page.getByLabel("New password", { exact: true }).fill("new-secure-password");
  await page.getByRole("button", { name: "Reset password", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Your password has been reset");
  await expect(page).toHaveURL(/\/reset-password$/);
  expect(await page.evaluate(() => localStorage.getItem("kruvim.rt"))).toBeNull();
});

test("verification requires confirmation and displays expired links", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/v1/auth/verify-email", async (route) => {
    calls++;
    await route.fulfill({ status: 400, json: { error: { code: "account_token_invalid", message: "This link is invalid or has expired." } } });
  });
  await page.goto(`/verify-email#token=${"x".repeat(64)}`);
  await expect(page.getByRole("button", { name: "Verify email", exact: true })).toBeVisible();
  expect(calls).toBe(0);
  await page.getByRole("button", { name: "Verify email", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("invalid or has expired");
  await page.getByRole("link", { name: "Request a new link" }).click();
  await expect(page).toHaveURL(/\/verification-email$/);
});
