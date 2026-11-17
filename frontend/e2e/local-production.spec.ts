import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
const evidence = path.resolve("../../kruvim-local-processing-evidence");

test("production app path serves document speech and frame workers with no original transfer", async ({ page }, info) => {
  const errors: string[] = []; const failures: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("response", r => { if (r.status() >= 400 && !r.url().includes("/api/")) failures.push(`${r.status()} ${r.url()}`); });
  await page.goto("login"); await page.getByLabel("Email").fill("demo@kruvim.local");
  await page.getByLabel("Password", { exact: true }).fill("kruvim-demo-2026");
  await page.getByRole("button", { name: "Sign in", exact: true }).click(); await expect(page).not.toHaveURL(/login/);
  const requests: { url: string; bytes: number; contentType?: string }[] = [];
  page.context().on("request", r => { if (!["GET", "HEAD", "OPTIONS"].includes(r.method())) requests.push({ url: r.url(), bytes: r.postDataBuffer()?.length || 0, contentType: r.headers()["content-type"] }); });
  const results: { name: string; bytes: number; images: number; transcript: boolean }[] = [];
  const cdp = await page.context().newCDPSession(page);
  for (const name of ["large-brief.pdf", "brief.docx", "large-image.png", "speech.wav", "large-video.mp4"]) {
    await page.goto("http://127.0.0.1:5187/app/");
    await page.getByLabel("Content file", { exact: true }).setInputFiles(path.join(evidence, "fixtures", name));
    if (name.endsWith("mp4")) await page.getByLabel(/Transcript, subtitles or script/).fill("00:00:00,000 --> 00:00:20,000\nA breakfast recipe, locally prepared.");
    await page.getByRole("button", { name: "Prepare and review draft", exact: true }).click();
    if (name === "large-image.png") await cdp.send("Memory.simulatePressureNotification", { level: "critical" });
    await expect(page.getByRole("dialog")).toBeVisible({ timeout: 180000 });
    const sending = page.waitForRequest(r => /projects\/[^/]+\/simulations$/.test(r.url()) && r.method() === "POST");
    await page.getByRole("button", { name: "Send reviewed content to cloud" }).click();
    const request = await sending; const content = request.postDataJSON().content;
    expect(content.asset_id).toBeNull(); expect(content.asset_ids).toEqual([]);
    if (name.endsWith("pdf") || name.endsWith("docx")) expect(content.text).toContain("Kruvim");
    if (name.endsWith("wav")) expect(content.transcript.toLowerCase()).toContain("cloud");
    if (name.endsWith("png") || name.endsWith("mp4")) expect(content.local_media.images.length).toBeGreaterThan(0);
    await expect(page).toHaveURL(/app\/simulations\/[a-f0-9]+$/);
    results.push({ name, bytes: request.postDataBuffer()!.length, images: content.local_media?.images.length || 0, transcript: !!content.transcript });
  }
  expect(requests.every(r => !/assets\/(upload|complete)/.test(r.url) && !r.contentType?.includes("multipart") && r.bytes < 1500000)).toBeTruthy();
  expect(errors).toEqual([]); expect(failures).toEqual([]);
  fs.writeFileSync(path.join(evidence, `${info.project.name}-production.json`), JSON.stringify({ results, requests, errors, failures, memoryPressure: "CDP critical notification during large-image preparation; not a physical low-RAM machine" }, null, 2));
});
