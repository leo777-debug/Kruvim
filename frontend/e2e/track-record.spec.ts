import { test, expect } from "@playwright/test";
import { completedSimulation } from "./helpers";

test("a forecast is created, locked into the ledger, proven and shown honestly", async ({ page, request }, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await completedSimulation(request);
  await page.goto("/login");
  await page.getByLabel("Email").fill("demo@kruvim.local");
  await page.getByLabel("Password").fill("kruvim-demo-2026");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/login/);

  await page.goto("/track-record");
  await page.getByRole("button", { name: "New forecast" }).click();
  const question = `Will the ${info.project.name} launch land well?`;
  await page.getByLabel("Question").fill(question);
  await page.getByRole("combobox", { name: "Simulation that answers it" }).click();
  await page.getByRole("option").nth(1).click();
  const due = new Date(Date.now() + 14 * 86_400_000).toISOString().slice(0, 10);
  await page.getByLabel("Resolves on").fill(due);
  await page.getByLabel("How it will be measured").fill("Mean rated reaction of the first 300 public comments in week one.");
  await page.getByLabel("Model training cutoff").fill("2026-01-31");
  await page.getByRole("button", { name: "Save draft" }).click();

  const row = page.getByRole("row").filter({ hasText: question });
  await row.getByRole("button", { name: "Lock" }).click();
  await expect(row.getByText("locked")).toBeVisible();
  await expect(row.getByText(/^#[0-9a-f]{10}$/)).toBeVisible();
  await expect(row.getByText("Doesn't count: Dry-run prediction")).toBeVisible();   // honest about dry runs
  const download = page.waitForEvent("download");
  await row.getByRole("button", { name: `Download proof for: ${question}` }).click();
  expect((await download).suggestedFilename()).toMatch(/^kruvim-forecast-proof-.+\.json$/);
  await expect(page.getByText(/entries · head [0-9a-f]{16}/)).toBeVisible();

  await page.goto("/record");
  await expect(page.getByText("Not published yet")).toBeVisible();
  expect(errors).toEqual([]);
});
