import { test, expect, type Page } from "@playwright/test";

async function passwordManager(page: Page, behavior: "save" | "reject" | "unsupported" = "save") {
  await page.addInitScript((behavior) => {
    const w = window as any;
    w.savedPasswords = [];
    Object.defineProperty(window, "PasswordCredential", { configurable: true, value: behavior === "unsupported" ? undefined : class {
      constructor(data: object) { Object.assign(this, data); }
    } });
    Object.defineProperty(navigator, "credentials", { configurable: true, value: {
      store: async (credential: unknown) => {
        if (behavior === "reject") throw new Error("Password saving disabled");
        w.savedPasswords.push(credential);
        return credential;
      },
    } });
  }, behavior);
}

test("a newly created account can sign out and sign in with its original password", async ({ page }) => {
  await passwordManager(page);
  const email = `roundtrip-${Date.now()}@example.com`;
  const password = " Exact-Password-عربي-2026! ";
  await page.goto("/register");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Your name", { exact: true }).fill("Roundtrip user");
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page).not.toHaveURL(/register/);
  const refreshToken = await page.evaluate(() => localStorage.getItem("kruvim.rt"));
  expect((await page.request.post("/api/v1/auth/logout", { data: { refresh_token: refreshToken } })).ok()).toBe(true);
  await page.evaluate(() => localStorage.removeItem("kruvim.rt"));
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill(email.toUpperCase());
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/login/);
});

test("autofilled signup credentials survive updates to other form controls", async ({ page }) => {
  await passwordManager(page);
  await page.goto("/register");
  const email = `autofill-${Date.now()}@example.com`;
  const password = "browser-generated-password-2026";
  await page.getByLabel("Email", { exact: true }).evaluate((input: HTMLInputElement, value) => { input.value = value; }, email);
  await page.getByLabel("Password", { exact: true }).evaluate((input: HTMLInputElement, value) => { input.value = value; }, password);
  await page.getByLabel("Save password in this browser").uncheck();
  await expect(page.getByLabel("Email", { exact: true })).toHaveValue(email);
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue(password);
  const request = page.waitForRequest("**/api/v1/auth/register");
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  expect((await request).postDataJSON()).toMatchObject({ email, password });
  await expect(page).not.toHaveURL(/register/);
  expect((await page.request.post("/api/v1/auth/login", { data: { email, password } })).ok()).toBe(true);
});

test("registration offers to save credentials after the account is created", async ({ page }) => {
  await passwordManager(page);
  await page.goto("/register");
  const email = `saved-${Date.now()}@example.com`;
  await page.getByLabel("Email", { exact: true }).fill(email);
  await expect(page.getByLabel("Email", { exact: true })).toHaveAttribute("autocomplete", "username");
  await expect(page.getByLabel("Password", { exact: true })).toHaveAttribute("autocomplete", "new-password");
  await page.getByLabel("Password", { exact: true }).fill("saved-password-2026");
  await expect(page.getByLabel("Save password in this browser")).toBeChecked();
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page).not.toHaveURL(/register/);
  expect(await page.evaluate(() => (window as any).savedPasswords)).toEqual([
    expect.objectContaining({ id: email, password: "saved-password-2026" }),
  ]);
  const storage = await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }));
  expect(storage).not.toContain("saved-password-2026");
  await page.reload();
  await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => !!localStorage.getItem("kruvim.rt"))).toBe(true);
});

test("sign-in submits browser autofill values and saves only valid credentials", async ({ page }) => {
  await passwordManager(page);
  await page.goto("/login");
  await expect(page.getByLabel("Password", { exact: true })).toHaveAttribute("autocomplete", "current-password");
  await page.getByLabel("Email", { exact: true }).fill("demo@kruvim.local");
  await page.getByLabel("Password", { exact: true }).fill("wrong-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByText("Wrong email or password.", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => (window as any).savedPasswords)).toEqual([]);
  // Model a password manager populating the DOM without dispatching change events.
  await page.getByLabel("Password", { exact: true }).evaluate((input: HTMLInputElement) => { input.value = "kruvim-demo-2026"; });
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/login/);
  expect(await page.evaluate(() => (window as any).savedPasswords)).toEqual([
    expect.objectContaining({ id: "demo@kruvim.local", password: "kruvim-demo-2026" }),
  ]);
});

for (const behavior of ["unchecked", "reject", "unsupported"] as const) {
  test(`sign-in succeeds when password saving is ${behavior}`, async ({ page }) => {
    await passwordManager(page, behavior === "unchecked" ? "save" : behavior);
    await page.goto("/login");
    await page.getByLabel("Email", { exact: true }).fill("demo@kruvim.local");
    await page.getByLabel("Password", { exact: true }).fill("kruvim-demo-2026");
    if (behavior === "unchecked") await page.getByLabel("Save password in this browser").uncheck();
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page).not.toHaveURL(/login/);
    expect(await page.evaluate(() => (window as any).savedPasswords)).toEqual([]);
  });
}
