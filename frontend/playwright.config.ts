/**
 * Playwright config (Phase 1-E F2-S3).
 *
 * 撮影台本 docs/META_APP_REVIEW_SCREENCAST_SCRIPT.md の 7 シーン + Data Deletion を
 * frontend E2E でカバーする。実機 Meta OAuth は通さず、API レイヤを mock する。
 *
 * - baseURL: Vite dev server (localhost:5173)
 * - browser: chromium 単体（CI 時間短縮 / multi-browser は後追い）
 * - webServer: 自動で `npm run dev` を起動する
 * - retain-on-failure: trace / video / screenshot を artifact 化
 *
 * 使い方:
 *   npm run test:e2e:install   # browser を一度だけ install
 *   npm run test:e2e
 *   npm run test:e2e:ui        # interactive UI mode
 */

import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.PORT || 5173);
const BASE_URL = process.env.E2E_BASE_URL || `http://localhost:${PORT}`;

export default defineConfig({
  testDir: "./tests-e2e",
  // Sprint 7 撮影台本に対応する 8 spec を一括実行する想定
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // CI / local どちらも単一 worker。webServer 共有の race を避ける
  workers: 1,
  reporter: process.env.CI
    ? [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]]
    : [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],

  use: {
    baseURL: BASE_URL,
    // CI のフレーク削減: trace を毎回 retain（失敗時 artifact 化）
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  // Vite dev server を自動起動する。E2E 用の env で Firebase config を空にし、
  // tests-e2e/utils/auth.ts の addInitScript と組み合わせて認証を bypass する。
  webServer: process.env.E2E_NO_WEBSERVER
    ? undefined
    : {
        command: "npm run dev -- --port " + PORT,
        url: BASE_URL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        env: {
          // Firebase 実機 IDP に飛ばないようダミー値を設定（mock により無視される）
          VITE_FIREBASE_API_KEY: "AIzaSyE2E-dummy-api-key",
          VITE_FIREBASE_AUTH_DOMAIN: "e2e-fixture.firebaseapp.com",
          VITE_GCP_PROJECT_ID: "e2e-fixture",
        },
      },
});
