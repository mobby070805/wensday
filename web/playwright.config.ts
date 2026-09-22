import { defineConfig } from "@playwright/test";

/**
 * Real-browser validation against a real running backend + web dev server (both started
 * manually — this config does not manage them, since the backend isn't a `npm` process).
 * Set PLAYWRIGHT_BASE_URL to override the default http://localhost:3100.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3100",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  reporter: [["list"]],
});
