import { defineConfig } from "@playwright/test";
import base from "./playwright.config";
const backend = Array.isArray(base.webServer) ? base.webServer[0] : base.webServer;
export default defineConfig({ testDir: "./e2e", testMatch: "local-production.spec.ts", timeout: 300000, workers: 1, retries: 0,
  webServer: [{ ...backend!, url: "http://127.0.0.1:8019/healthz", env: { KRUVIM_VERIFY_PORT: "8019" } }, { command: "npm run build -- --base=/app/ --outDir dist-local-production && npm run preview -- --base=/app/ --outDir dist-local-production --host 127.0.0.1 --port 5187 --strictPort",
    url: "http://127.0.0.1:5187/app/", timeout: 360000, reuseExistingServer: false,
    env: { KRUVIM_API_URL: "http://127.0.0.1:8019" } }],
  outputDir: "test-results-local-production", use: { baseURL: "http://127.0.0.1:5187/app/", trace: "retain-on-failure", viewport: { width: 1440, height: 1000 } },
  projects: [{ name: "local-production", use: { channel: process.env.KRUVIM_BROWSER_CHANNEL || undefined } }],
});
