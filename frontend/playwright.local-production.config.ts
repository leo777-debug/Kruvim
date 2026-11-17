import { defineConfig } from "@playwright/test";
export default defineConfig({ testDir: "./e2e", testMatch: "local-production.spec.ts", timeout: 300000, workers: 1, retries: 0,
  outputDir: "test-results-local-production", use: { baseURL: "http://127.0.0.1:5187/app/", trace: "retain-on-failure", viewport: { width: 1440, height: 1000 } },
  projects: [{ name: "edge", use: { channel: "msedge" } }, { name: "chrome", use: { channel: "chrome" } }],
});
