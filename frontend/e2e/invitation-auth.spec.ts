import { test, expect, type APIRequestContext } from "@playwright/test";

const password = "recipient-password-2026";

async function register(request: APIRequestContext, prefix: string) {
  const response = await request.post("/api/v1/auth/register", { data: {
    email: `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}@example.com`,
    password, name: prefix,
  } });
  expect(response.ok()).toBe(true);
  return response.json();
}

async function invite(request: APIRequestContext, owner: any, email: string) {
  const response = await request.post("/api/v1/members/invites", {
    headers: { Authorization: `Bearer ${owner.access_token}` }, data: { email, role: "member" },
  });
  expect(response.ok()).toBe(true);
  return (await response.json()).accept_url.split("/invite/")[1];
}

test("existing recipient must authenticate before the browser stores a session", async ({ page, request }) => {
  const owner = await register(request, "inviter");
  const recipient = await register(request, "recipient");
  const token = await invite(request, owner, recipient.user.email);
  await page.goto(`/invite/${token}`);
  const input = page.getByLabel("Password", { exact: true });
  await expect(input).toHaveAttribute("required", "");
  await page.getByRole("button", { name: "Accept invite" }).click();
  await expect(page).toHaveURL(new RegExp(`/invite/${token}$`));
  expect(await page.evaluate(() => localStorage.getItem("kruvim.rt"))).toBeNull();

  await input.fill("wrong-recipient-password");
  const rejected = page.waitForResponse(r => r.url().endsWith("/auth/invites/accept"));
  await page.getByRole("button", { name: "Accept invite" }).click();
  expect((await rejected).status()).toBe(401);
  await expect(page.getByText("Wrong password or account disabled.", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("kruvim.rt"))).toBeNull();

  // Browser autofill may set the DOM value without dispatching a change event.
  await input.evaluate((element: HTMLInputElement, value) => { element.value = value; }, password);
  const accepted = page.waitForResponse(r => r.url().endsWith("/auth/invites/accept"));
  await page.getByRole("button", { name: "Accept invite" }).click();
  const response = await accepted;
  expect(response.status()).toBe(200);
  expect((await response.json()).user.id).toBe(recipient.user.id);
  await expect(page).toHaveURL(/\/(home)?$/);
  await expect.poll(() => page.evaluate(() => !!localStorage.getItem("kruvim.rt"))).toBe(true);
});

test("new recipient can create an account from the invitation form", async ({ page, request }) => {
  const owner = await register(request, "new-inviter");
  const email = `new-recipient-${Date.now()}-${Math.random().toString(16).slice(2)}@example.com`;
  const token = await invite(request, owner, email);
  await page.goto(`/invite/${token}`);
  await page.getByLabel("Your name", { exact: true }).fill("New recipient");
  await page.getByLabel("Password", { exact: true }).fill(password);
  const accepted = page.waitForResponse(r => r.url().endsWith("/auth/invites/accept"));
  await page.getByRole("button", { name: "Accept invite" }).click();
  const response = await accepted;
  expect(response.status()).toBe(200);
  const session = await response.json();
  expect(session.user.email).toBe(email);
  expect(session.user.name).toBe("New recipient");
  expect(session.orgs).toHaveLength(1);
  expect(session.orgs[0]).toMatchObject({ id: owner.orgs[0].id, role: "member" });
  await expect(page).toHaveURL(/\/(home)?$/);
});
