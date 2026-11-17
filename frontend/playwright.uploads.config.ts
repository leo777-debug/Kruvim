import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e", testMatch: "direct-uploads.spec.ts", timeout: 60_000, workers: 1,
  use: { baseURL: "http://127.0.0.1:5191", ...devices["Desktop Chrome"],
    channel: process.env.KRUVIM_BROWSER_CHANNEL || (process.platform === "win32" ? "msedge" : undefined) },
  webServer: { command: "npm run dev -- --host 127.0.0.1 --port 5191 --strictPort",
    url: "http://127.0.0.1:5191", timeout: 60_000, reuseExistingServer: false },
});
