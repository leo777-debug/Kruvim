import { test, expect } from "@playwright/test";

test("a missing page chunk recovers the current deployment without signing out", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo@kruvim.local");
  await page.getByLabel("Password").fill("kruvim-demo-2026");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/login/);
  await page.goto("/help");
  await expect(page.getByRole("heading", { name: "How Kruvim works", exact: true })).toBeVisible();
  let failed = false;
  let documents = 0;
  page.on("request", request => { if (request.resourceType() === "document") documents++; });
  await page.route(/\/assets\/LibraryPage-[^/]+\.js$/, async route => {
    if (!failed) {
      failed = true;
      await route.fulfill({ status: 404, contentType: "text/javascript", body: "" });
    } else await route.continue();
  });
  await page.goto("/data-library");
  await expect(page.getByRole("heading", { name: "Data library", exact: true })).toBeVisible();
  expect(failed).toBe(true);
  expect(documents).toBe(2);
  await expect(page.getByLabel("New folder name")).toBeVisible();
});

test("a persistent chunk failure shows recovery controls without a reload loop", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo@kruvim.local");
  await page.getByLabel("Password").fill("kruvim-demo-2026");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/login/);
  await page.goto("/help");
  await expect(page.getByRole("heading", { name: "How Kruvim works", exact: true })).toBeVisible();
  await page.evaluate(() => sessionStorage.setItem("kruvim.page-recovery", String(Date.now())));
  let documents = 0;
  page.on("request", request => { if (request.resourceType() === "document") documents++; });
  await page.route(/\/assets\/LibraryPage-[^/]+\.js$/, route => route.fulfill({ status: 404, contentType: "text/javascript", body: "" }));
  await page.goto("/data-library");
  await expect(page.getByRole("alert")).toContainText("This page couldn’t open");
  await expect(page.getByRole("button", { name: "Reload Kruvim", exact: true })).toBeVisible();
  expect(documents).toBe(1);
});

test("restoring a session does not wait for a redundant account request", async ({ page }) => {
  // Exercise real refresh and authenticated APIs against the disposable DB.
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo@kruvim.local");
  await page.getByLabel("Password").fill("kruvim-demo-2026");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/login/);
  let accountRequests = 0;
  await page.route("**/api/v1/auth/me", async route => {
    accountRequests++;
    await route.abort();
  });
  await page.goto("/help");
  await expect(page.getByRole("heading", { name: "How Kruvim works", exact: true })).toBeVisible();
  expect(accountRequests).toBe(0);
});

test("the sidebar remains usable while the next page code is loading", async ({ page, isMobile }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo@kruvim.local");
  await page.getByLabel("Password").fill("kruvim-demo-2026");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/login/);
  await page.goto("/help");
  await expect(page.getByRole("heading", { name: "How Kruvim works", exact: true })).toBeVisible();

  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const libraryCode = /\/(?:src\/features\/datapool\/LibraryPage\.tsx|assets\/LibraryPage-[^/]+\.js)(?:\?.*)?$/;
  await page.route(libraryCode, async route => {
    await gate;
    await route.continue();
  });
  try {
    // This app uses its mobile sidebar at widths below lg.
    if (isMobile || page.viewportSize()!.width < 1024) await page.getByRole("button", { name: "Open navigation" }).click();
    const requested = page.waitForRequest(libraryCode);
    await page.getByRole("link", { name: "Data library", exact: true }).click();
    await requested;
    // Router transitions may retain the previous page instead of showing the
    // fallback. Either way the navigation must stay mounted and usable.
    const navigation = page.getByRole("navigation", { name: "Main navigation" });
    if (!(await navigation.isVisible())) await page.getByRole("button", { name: "Open navigation" }).click();
    await expect(navigation).toBeVisible();
  } finally {
    release();
  }
  await expect(page.getByRole("heading", { name: "Data library", exact: true })).toBeVisible();
  await expect(page.getByLabel("New folder name")).toBeVisible();
});
