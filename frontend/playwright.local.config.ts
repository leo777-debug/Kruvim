import { defineConfig } from "@playwright/test";
import base from "./playwright.config";
const backend = Array.isArray(base.webServer) ? base.webServer[0] : base.webServer;
export default defineConfig({ testDir: "./e2e", testMatch: "local-processing.spec.ts", timeout: 300000, workers: 1, retries: 0, outputDir: "test-results-local",
  webServer: [{ ...backend!, url: "http://127.0.0.1:8018/healthz", env: { KRUVIM_VERIFY_PORT: "8018" } },
    { command: "npm run dev -- --host 127.0.0.1 --port 5188 --strictPort", url: "http://127.0.0.1:5188",
      timeout: 90000, reuseExistingServer: false, env: { KRUVIM_API_URL: "http://127.0.0.1:8018" } }],
  use: { baseURL: "http://127.0.0.1:5188", trace: "retain-on-failure", viewport: { width: 1440, height: 1000 } },
  projects: [{ name: "local", use: { channel: process.env.KRUVIM_BROWSER_CHANNEL || undefined } }],
});
