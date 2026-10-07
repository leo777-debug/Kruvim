import { test, expect, type Page } from "@playwright/test";

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
}

test("short video completes, report opens and an interview is selected", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("requestfailed", (r) => { if (r.url().includes("/api/v1/") && !r.failure()?.errorText.includes("ERR_ABORTED")) errors.push(`${r.failure()?.errorText} ${r.url()}`); });
  page.on("response", (r) => { if (r.url().includes("/api/v1/") && r.status() >= 400) errors.push(`${r.status()} ${r.url()}`); });
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo@kruvim.local");
  await page.getByLabel("Password").fill("kruvim-demo-2026");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/login/);
  // Obtain the visible project's link through the UI; no auth fixture bypass.
  await page.goto("/projects");
  await page.getByText("Ramadan fitness campaign", { exact: true }).click();
  const path = new URL(page.url()).pathname;
  await page.goto(path + "/new");
  await expect(page.getByRole("heading", { name: /New simulation|New test/ })).toBeVisible();
  await page.getByLabel(/Transcript, subtitles or script/).fill("Make breakfast in one minute. Mix yogurt and oats, add banana, and enjoy. Follow for another simple recipe tomorrow.");
  const quick = page.getByRole("button", { name: "Quick", exact: true });
  if (await quick.count()) await quick.click();
  // The original editor and simple mode expose the same primary action.
  await page.getByRole("button", { name: /Create.*build|Test it/ }).click();
  await expect(page).toHaveURL(/simulations\/[a-f0-9]+/);
  const sid = new URL(page.url()).pathname.split("/").at(-1)!;
  // Complete legacy manual steps when the simple autopilot is not enabled yet.
  const advanced = page.getByRole("button", { name: "See how it works", exact: true });
  if (await advanced.count()) await advanced.click();
  const nextEnv = page.getByRole("button", { name: /Environment/ }).first();
  if (!(await advanced.count())) {
    await expect(nextEnv).toBeVisible();
    await expect(nextEnv).toBeEnabled();
    await nextEnv.click();
    const build = page.getByRole("button", { name: /Prepare environment/ });
    await expect(build).toBeVisible();
    await build.click();
    const start = page.getByRole("button", { name: /Start simulation/ });
    await expect(start).toBeEnabled();
    await start.click();
  }
  const interviews = page.getByRole("button", { name: /^.*Interviews/ }).first();
  await expect(interviews).toBeEnabled({ timeout: 120_000 });
  await page.getByRole("button", { name: /^.*Results/ }).first().click();
  await page.getByRole("button", { name: "Analyst report", exact: true }).click();
  await expect(page.locator(".prose-report h1")).toBeVisible();
  await expect(page.locator(".prose-report")).not.toContainText(/node:|edge:/);
  await noOverflow(page);
  await interviews.click();
  await expect(page).toHaveURL(new RegExp(`simulations/${sid}.*agent=`));
  await expect(page.getByPlaceholder("Ask anything, in any language…")).toBeVisible();
  await noOverflow(page);
  for (const route of ["/", "/my-audience", "/data-pool", "/projects", "/settings"]) {
    await page.goto(route);
    await expect(page.locator("h1").first()).toBeVisible();
    await noOverflow(page);
  }
  expect(errors).toEqual([]);
});
