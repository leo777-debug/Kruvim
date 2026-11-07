import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

// Verify production chunks rather than Vite's unbundled development modules.
const backend = Array.isArray(base.webServer) ? base.webServer[0] : base.webServer;
export default defineConfig({
  ...base,
  testMatch: /(?:page-loading|library)\.spec\.ts/,
  use: { ...base.use, baseURL: "http://127.0.0.1:5197" },
  webServer: [
    { ...backend!, url: "http://127.0.0.1:8027/healthz", env: { KRUVIM_VERIFY_PORT: "8027" } },
    { command: "npm run preview -- --host 127.0.0.1 --port 5197 --strictPort", url: "http://127.0.0.1:5197",
      timeout: 60_000, reuseExistingServer: false, env: { KRUVIM_API_URL: "http://127.0.0.1:8027" } },
  ],
});
