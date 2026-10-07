import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const py = process.env.KRUVIM_TEST_PYTHON || (process.platform === "win32" ? path.resolve("../backend/.venv/Scripts/python.exe") : "python");
export default defineConfig({
  testDir: "./e2e", timeout: 180_000, expect: { timeout: 30_000 }, workers: 1, retries: 0,
  use: { baseURL: "http://127.0.0.1:5186", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } } },
  ],
  webServer: [
    { command: `"${py}" -m tools.serve_verify`, cwd: "../backend", url: "http://127.0.0.1:8016/healthz", timeout: 90_000, reuseExistingServer: false,
      env: { KRUVIM_VERIFY_PORT: "8016" } },
    { command: "npm run dev -- --host 127.0.0.1 --port 5186 --strictPort", url: "http://127.0.0.1:5186", timeout: 60_000, reuseExistingServer: false,
      env: { KRUVIM_API_URL: "http://127.0.0.1:8016" } },
  ],
});
