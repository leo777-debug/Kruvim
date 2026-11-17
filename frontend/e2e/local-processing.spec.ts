import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import fs from "node:fs";
const fixture = (name: string) => path.resolve("../../kruvim-local-processing-evidence/fixtures", name);
const evidence = path.resolve("../../kruvim-local-processing-evidence");
async function login(page: Page) {
  await page.goto("/login"); await page.getByLabel("Email").fill("demo@kruvim.local");
  await page.getByLabel("Password", { exact: true }).fill("kruvim-demo-2026"); await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/login/);
}
async function prepare(page: Page, name: string, transcript = "") {
  await page.locator("#local-test-input").setInputFiles(fixture(name));
  return page.evaluate(async ({ transcript }) => {
    const m = await import(/* @vite-ignore */ "/src/lib/local/prepare.ts");
    const f = (document.querySelector("#local-test-input") as HTMLInputElement).files![0];
    const steps: string[] = []; const start = performance.now();
    try { const value = await m.prepareFile(f, new AbortController().signal, (s: string) => steps.push(s), transcript);
      return { value, ms: performance.now() - start, steps, size: f.size };
    } catch (e) { return { error: (e as Error).message, ms: performance.now() - start, steps, size: f.size }; }
  }, { transcript });
}
const redact = (result: any) => ({ ...result, value: result.value ? { ...result.value, local_media: { ...result.value.local_media, images: result.value.local_media.images.map((im: any) => ({ ...im, data: `[resized JPEG ${im.data.length} chars]` })) } } : undefined });

test("real documents images media and local failure boundaries", async ({ page }, info) => {
  const sent: { method: string; url: string; bytes: number }[] = [];
  page.context().on("request", r => { if (!["GET", "HEAD", "OPTIONS"].includes(r.method())) sent.push({ method: r.method(), url: r.url(), bytes: r.postDataBuffer()?.length || 0 }); });
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  await page.goto("/login");
  await page.evaluate(() => { const i = document.createElement("input"); i.type = "file"; i.id = "local-test-input"; document.body.append(i); });
  const results: Record<string, unknown> = {};
  for (const name of ["brief.md", "brief.pdf", "large-brief.pdf", "brief.docx", "slide-red.png", "slide-blue.jpg", "large-image.png", "large-video.mp4", "broken.pdf"]) {
    const result = await prepare(page, name, name.endsWith("mp4") ? "00:00:00,000 --> 00:00:20,000\nA breakfast recipe with oats and banana." : "");
    results[name] = redact(result);
    fs.writeFileSync(path.join(evidence, `${info.project.name}-local.json`), JSON.stringify({ browser: await page.evaluate(() => navigator.userAgent), results, sent, errors }, null, 2));
    if (name === "broken.pdf") expect(result.error).toBeTruthy();
    else { expect(result.error, JSON.stringify(result)).toBeUndefined(); expect(result.value).toBeTruthy(); if (name.startsWith("brief.")) expect(result.value.text).toMatch(/Kruvim|Brand/); }
    if (name === "large-video.mp4") { expect(result.size).toBeGreaterThan(50 * 1024 * 1024); expect(result.value.local_media.images.length).toBeGreaterThan(0); expect(result.value.local_media.duration).toBeCloseTo(20, 0); }
  }
  const speech = await prepare(page, "speech.wav"); results.speech = speech;
  expect(speech.error, JSON.stringify(speech)).toBeUndefined();
  const largeAudio = await prepare(page, "large-audio.wav"); results.largeAudio = largeAudio;
  expect(largeAudio.error, JSON.stringify(largeAudio)).toBeUndefined();
  expect(largeAudio.size).toBeGreaterThan(50 * 1024 * 1024);
  expect(largeAudio.value.transcript.toLowerCase()).toContain("cloud");
  const videoSpeech = await prepare(page, "large-video.mp4"); results.videoSpeech = redact(videoSpeech);
  expect(videoSpeech.error, JSON.stringify(videoSpeech)).toBeUndefined();
  expect(videoSpeech.value.transcript.toLowerCase()).toContain("cloud");
  // Block every external origin: model cache must suffice, while Vite still
  // serves runtime code. This does not claim an offline-installable website.
  await page.context().route("https://**/*", route => route.abort());
  const cachedSpeech = await prepare(page, "speech.wav"); results.cachedSpeech = cachedSpeech;
  expect(cachedSpeech.error, JSON.stringify(cachedSpeech)).toBeUndefined();
  fs.writeFileSync(path.join(evidence, `${info.project.name}-local.json`), JSON.stringify({ browser: await page.evaluate(() => navigator.userAgent), results, sent, errors }, null, 2));
  expect(speech.error, JSON.stringify(speech)).toBeUndefined();
  expect(speech.value.transcript.toLowerCase()).toContain("cloud");
  expect(sent).toEqual([]); expect(errors).toEqual([]);
});

test("carousel order and A/B survive review save and edit", async ({ page }, info) => {
  await login(page); await page.goto("/projects");
  await page.getByText("Ramadan fitness campaign", { exact: true }).click();
  await page.goto(new URL(page.url()).pathname + "/new");
  await page.getByRole("button", { name: "More options", exact: true }).click();
  await page.getByRole("button", { name: /Carousel.*2 to 10 slides/ }).click();
  await page.getByRole("button", { name: "Another version of mine", exact: true }).click();
  const inputs = page.locator('input[type="file"][multiple]');
  await inputs.nth(0).setInputFiles([fixture("slide-red.png"), fixture("slide-blue.jpg")]);
  await inputs.nth(1).setInputFiles([fixture("slide-blue.jpg"), fixture("slide-red.png")]);
  await page.getByRole("button", { name: "Prepare and review draft", exact: true }).click();
  await expect(page.getByRole("dialog").locator("figure img")).toHaveCount(4);
  const before = await page.getByRole("dialog").locator("figure img").evaluateAll(imgs => imgs.map(im => (im as HTMLImageElement).src));
  const request = page.waitForRequest(r => /projects\/[^/]+\/simulations$/.test(r.url()) && r.method() === "POST");
  await page.getByRole("button", { name: "Send reviewed content to cloud" }).click();
  const body = (await request).postDataJSON();
  expect(body.content.local_media.images.map((im: any) => im.data)).toEqual(before.slice(0, 2));
  expect(body.content.variant_b.local_media.images.map((im: any) => im.data)).toEqual(before.slice(2));
  expect(before[0]).not.toEqual(before[1]); expect(before[0]).toEqual(before[3]);
  await expect(page).toHaveURL(/simulations\/[a-f0-9]+$/);
  await page.goto(new URL(page.url()).pathname + "/edit");
  await page.getByRole("button", { name: "Prepare and review draft", exact: true }).click();
  await expect(page.getByRole("dialog").locator("figure img")).toHaveCount(4);
  expect(await page.getByRole("dialog").locator("figure img").evaluateAll(imgs => imgs.map(im => (im as HTMLImageElement).src))).toEqual(before);
  fs.writeFileSync(path.join(evidence, `${info.project.name}-carousel.json`), JSON.stringify({ versionA: body.content.local_media.images.map((im: any) => im.order), versionB: body.content.variant_b.local_media.images.map((im: any) => im.order), preservedAfterEdit: true }, null, 2));
});

test("background text review and large video reach existing cloud simulation without originals", async ({ page }, info) => {
  await login(page);
  const requests: { url: string; method: string; bytes: number; contentType?: string }[] = [];
  let simulationBody: any;
  page.context().on("request", r => {
    if (!["GET", "HEAD", "OPTIONS"].includes(r.method())) {
      requests.push({ url: r.url(), method: r.method(), bytes: r.postDataBuffer()?.length || 0, contentType: r.headers()["content-type"] });
      if (/projects\/[^/]+\/simulations$/.test(r.url())) simulationBody = r.postDataJSON();
    }
  });
  await page.goto("/projects"); await page.getByText("Ramadan fitness campaign", { exact: true }).click();
  const projectPath = new URL(page.url()).pathname;
  await page.getByLabel("Local background document").setInputFiles(fixture("brief.pdf"));
  await expect(page.getByRole("dialog")).toBeVisible(); expect(requests.filter(r => !r.url.endsWith("/auth/refresh"))).toEqual([]);
  await expect(page.getByLabel("Extracted document text")).toHaveValue(/Kruvim local PDF context/);
  await page.getByRole("button", { name: "Send reviewed text to cloud" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(page.getByText("brief.pdf", { exact: true }).first()).toBeVisible();
  await page.goto(projectPath + "/new");
  await page.getByLabel("Content file", { exact: true }).setInputFiles(fixture("large-video.mp4"));
  await page.getByLabel(/Transcript, subtitles or script/).fill("00:00:00,000 --> 00:00:20,000\nA breakfast recipe with oats and banana.");
  await page.getByRole("button", { name: "Prepare and review test", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible(); expect(simulationBody).toBeUndefined();
  expect(await page.getByRole("dialog").locator("figure img").count()).toBeGreaterThanOrEqual(2);
  while (await page.getByRole("button", { name: "Remove image", exact: true }).count() > 1) await page.getByRole("button", { name: "Remove image", exact: true }).first().click();
  await page.screenshot({ path: path.join(evidence, `${info.project.name}-review.png`), fullPage: true });
  await page.getByRole("button", { name: "Send reviewed content to cloud" }).click();
  await expect(page).toHaveURL(/simulations\/[a-f0-9]+$/);
  expect(simulationBody.content.local_media.images).toHaveLength(1);
  expect(simulationBody.content.local_media.images[0].time).toBeGreaterThan(10);
  expect(simulationBody.content.asset_id).toBeNull();
  await expect(page.getByLabel("Verdict")).toBeVisible({ timeout: 180000 });
  expect(requests.every(r => !/assets\/(upload|complete)/.test(r.url) && !r.contentType?.includes("multipart") && r.bytes < 1500000)).toBeTruthy();
  fs.writeFileSync(path.join(evidence, `${info.project.name}-flow.json`), JSON.stringify({ requests, content: { ...simulationBody.content, local_media: redact({ value: { ...simulationBody.content, local_media: simulationBody.content.local_media } }).value.local_media } }, null, 2));
});

test("cancellation unsupported browser low memory and broken media never send files", async ({ page }, info) => {
  await page.goto("/login");
  const sent: string[] = []; page.context().on("request", r => { if (!["GET", "HEAD", "OPTIONS"].includes(r.method())) sent.push(r.url()); });
  const results = await page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ "/src/lib/local/prepare.ts");
    const messages: string[] = [];
    const run = async (file: File, ctrl = new AbortController()) => { try { await m.prepareFile(file, ctrl.signal, () => {}); return "unexpected success"; } catch(e) { return (e as Error).message; } };
    const resources = new Set<string>();
    const createURL = URL.createObjectURL.bind(URL), revokeURL = URL.revokeObjectURL.bind(URL);
    URL.createObjectURL = blob => { const u = createURL(blob); resources.add(u); return u; };
    URL.revokeObjectURL = u => { resources.delete(u); revokeURL(u); };
    const ctrl = new AbortController(); const reading = run(new File(["a".repeat(60000)], "cancel.txt"), ctrl); ctrl.abort(); messages.push(await reading);
    const original = globalThis.Worker; Object.defineProperty(globalThis, "Worker", { configurable: true, value: undefined });
    messages.push(await run(new File(["hello"], "text.txt"))); Object.defineProperty(globalThis, "Worker", { configurable: true, value: original });
    Object.defineProperty(navigator, "deviceMemory", { configurable: true, value: 2 }); messages.push(await run(new File(["hello"], "text.txt"))); delete (navigator as any).deviceMemory;
    const wasm = globalThis.WebAssembly; Object.defineProperty(globalThis, "WebAssembly", { configurable: true, value: undefined });
    messages.push(await run(new File(["hello"], "text.txt"))); Object.defineProperty(globalThis, "WebAssembly", { configurable: true, value: wasm });
    class FailedWorker {
      onerror: (() => void) | null = null; onmessage = null;
      postMessage() { queueMicrotask(() => this.onerror?.()); }
      terminate() {}
    }
    Object.defineProperty(globalThis, "Worker", { configurable: true, value: FailedWorker });
    messages.push(await run(new File(["hello"], "allocation-failure.txt")));
    Object.defineProperty(globalThis, "Worker", { configurable: true, value: original });
    const megabyte = new Blob([new Uint8Array(1024 * 1024)]);
    messages.push(await run(new File(Array(129).fill(megabyte), "too-large.wav", { type: "audio/wav" })));
    messages.push(await run(new File(["invalid video bytes"], "bad.mp4", { type: "video/mp4" })));
    messages.push(await run(new File([new Uint8Array([255, 254, 255])], "invalid-utf8.txt")));
    messages.push(await run(new File(["broken zip"], "broken.docx")));
    messages.push(await run(new File(["a".repeat(60001)], "long.txt")));
    messages.push(resources.size ? "unexpected success: leaked object URLs" : "No temporary object URLs remain");
    URL.createObjectURL = createURL; URL.revokeObjectURL = revokeURL;
    return messages;
  });
  expect(results.join(" ")).not.toContain("unexpected success"); expect(sent).toEqual([]);
  fs.writeFileSync(path.join(evidence, `${info.project.name}-failures.json`), JSON.stringify({ results, sent }, null, 2));
});

test("visible cancellation and a blocked first model download offer transcript fallback", async ({ page }, info) => {
  await login(page);
  await page.goto("/projects"); await page.getByText("Ramadan fitness campaign", { exact: true }).click();
  await page.goto(new URL(page.url()).pathname + "/new");
  const sent: string[] = [];
  page.context().on("request", r => { if (!["GET", "HEAD", "OPTIONS"].includes(r.method()) && /assets|\/simulations$/.test(r.url())) sent.push(r.url()); });
  await page.getByLabel("Content file", { exact: true }).setInputFiles(fixture("large-audio.wav"));
  await page.getByRole("button", { name: "Prepare and review draft", exact: true }).click();
  await page.getByRole("button", { name: "Cancel local processing", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(/abort|cancel/i);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(sent).toEqual([]);
  // This test has its own browser context, without the model cache from other tests.
  await page.context().route("https://**/*", route => route.abort());
  await page.getByLabel("Content file", { exact: true }).setInputFiles(fixture("speech.wav"));
  await page.getByRole("button", { name: "Prepare and review draft", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(/Paste an SRT\/VTT transcript/, { timeout: 90000 });
  expect(sent).toEqual([]);
  fs.writeFileSync(path.join(evidence, `${info.project.name}-cancel-download.json`), JSON.stringify({ visibleError: await page.getByRole("alert").innerText(), sent }, null, 2));
});
