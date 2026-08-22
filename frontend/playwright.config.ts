import { readFileSync } from "node:fs";

import { defineConfig, devices } from "@playwright/test";

/**
 * Browser end-to-end tests — docs/20.
 *
 * These start the **real backend** and the **real Vite dev server** and drive Chromium
 * against them. That is the point: every other layer stubs something, and a browser test
 * that stubs the API only proves the components render.
 *
 * The backend runs with `AUTH_MODE=dev` so no Cognito pool is needed, and with a
 * `GEMINI_API_KEY` if one is present. Specs that need a real model answer are tagged
 * `@live` and skip without a key, so the suite is useful either way.
 */
const BACKEND = "http://127.0.0.1:8000";
const FRONTEND = "http://127.0.0.1:5173";

/**
 * Decide whether the `@live` specs can run, by asking the same question the backend
 * will: is there a usable Gemini key in `backend/.env`?
 *
 * The key is deliberately **not** forwarded into the server's environment. The backend
 * loads `.env` itself, so passing it again adds nothing but a chance to corrupt it — and
 * that is exactly what happened: a `grep`-and-`cut` one-liner matched both the real key
 * and a commented-out one, produced a two-line value, and every model call failed with
 * "Illegal header value". The visible symptom was three live tests timing out on a
 * checkpoint that the API was emitting correctly all along.
 */
function hasGeminiKey(): boolean {
  if (process.env.GEMINI_API_KEY) return true;
  try {
    return readFileSync(new URL("../backend/.env", import.meta.url), "utf8")
      .split("\n")
      .some((line) => /^\s*GEMINI_API_KEY\s*=\s*\S+/.test(line));
  } catch {
    return false;
  }
}

if (hasGeminiKey()) process.env.CCOA_E2E_LIVE = "1";

export default defineConfig({
  // Surfaced to the specs so `npx playwright test` needs no environment fiddling.

  testDir: "./e2e",
  fullyParallel: false, // one backend, one SQLite file, one writer
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],

  use: {
    baseURL: FRONTEND,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      testIgnore: /mobile\.spec\.ts/,
    },
    {
      // The layout is mobile-first, so a phone is a first-class target rather than a
      // narrow desktop: at this width the two rails are sheets and the header buttons
      // are the only way to reach them. Nothing in the desktop project exercises that.
      name: "mobile",
      use: { ...devices["Pixel 5"] },
      testMatch: /mobile\.spec\.ts/,
    },
  ],

  webServer: [
    {
      // `uv run` from the backend directory, so the venv and .env resolve exactly as
      // they do when a developer runs it by hand.
      command: "uv run uvicorn app.main:app --host 127.0.0.1 --port 8000",
      cwd: "../backend",
      url: `${BACKEND}/healthz`,
      // Deliberately NOT reused, even locally. A backend left running from an earlier
      // session answers the health check happily while serving code from before the
      // change under test — which produced seven confident failures against a frontend
      // that was correct. If a developer already has one running, Playwright says the
      // port is taken, and that is a far better error than a phantom regression.
      reuseExistingServer: false,
      timeout: 120_000,
      // No GEMINI_API_KEY here on purpose — see hasGeminiKey() above.
      env: { ENVIRONMENT: "local", AUTH_MODE: "dev", LOG_LEVEL: "WARNING" },
    },
    {
      command: "npm run dev",
      url: FRONTEND,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
