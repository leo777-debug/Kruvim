import { expect, test } from "@playwright/test";

test("a 6 MB file goes to storage and completion retries without resending bytes", async ({ page }) => {
  let transfers = 0;
  let completions = 0;
  const appBodies: number[] = [];
  await page.route("**/api/v1/projects/p/assets/upload", async (route) => {
    const request = route.request();
    appBodies.push(request.postDataBuffer()!.length);
    expect(request.postDataJSON()).toMatchObject({ filename: "video.mp4", size: 6_000_000, mime: "video/mp4" });
    await route.fulfill({ json: { transport: "direct", url: "https://storage.example/upload", method: "PUT",
      headers: { "Content-Type": "video/mp4" }, ticket: "upload-receipt" } });
  });
  await page.route("https://storage.example/upload", async (route) => {
    const request = route.request();
    expect(request.headers()["authorization"]).toBeUndefined();
    expect(request.headers()["x-org-id"]).toBeUndefined();
    expect(request.postDataBuffer()!.length).toBe(6_000_000);
    transfers++;
    await route.fulfill({ status: 200, body: "{}", headers: { "access-control-allow-origin": "*" } });
  });
  await page.route("**/api/v1/projects/p/assets/complete", async (route) => {
    appBodies.push(route.request().postDataBuffer()!.length);
    completions++;
    await route.fulfill(completions === 1 ? { status: 503, json: { error: { message: "Transient failure" } } }
      : { json: { id: "asset", size: 6_000_000 } });
  });
  await page.goto("/login");
  const result = await page.evaluate(async () => {
    const apiPath = "/src/lib/api.ts";
    const authPath = "/src/lib/auth.ts";
    const { useAuth } = await import(authPath);
    useAuth.setState({ accessToken: "app-session-marker", orgId: "workspace" });
    const { uploadAsset } = await import(apiPath);
    return uploadAsset("p", new File([new Uint8Array(6_000_000)], "video.mp4", { type: "video/mp4" }));
  });
  expect(result.id).toBe("asset");
  expect(transfers).toBe(1);
  expect(completions).toBe(2);
  expect(Math.max(...appBodies)).toBeLessThan(1024);
});

test("storage failure never creates an attachment", async ({ page }) => {
  let completions = 0;
  await page.route("**/api/v1/projects/p/assets/upload", (route) => route.fulfill({ json: {
    transport: "direct", url: "https://storage.example/failed", method: "PUT", headers: {}, ticket: "receipt" } }));
  await page.route("https://storage.example/failed", (route) => route.fulfill({ status: 413, body: "too large" }));
  await page.route("**/api/v1/projects/p/assets/complete", (route) => { completions++; return route.fulfill({ json: {} }); });
  await page.goto("/login");
  const message = await page.evaluate(async () => {
    const path = "/src/lib/api.ts";
    const { uploadAsset } = await import(path);
    try { await uploadAsset("p", new File(["bytes"], "file.mp4", { type: "video/mp4" })); }
    catch (error) { return (error as Error).message; }
  });
  expect(message).toContain("File upload failed");
  expect(completions).toBe(0);
});
