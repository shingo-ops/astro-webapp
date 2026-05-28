/**
 * ADR-038 / QA Smoke Suite — Playwright config (実 VPS backend 直叩き)
 *
 * frontend/tests-e2e/playwright.config.ts (Meta App Review 撮影用 mock e2e) とは
 * 別資産。ここでは:
 *   - **mock しない** — 実 frontend (https://app.salesanchor.jp) + 実 API
 *     (https://api.salesanchor.jp) に対して Playwright が動く
 *   - webServer は起動しない (本番が常時稼働している前提)
 *   - 認証は qa-tenant-creds.ts に書かれた 3 ユーザー (admin/staff/viewer) で
 *     real Firebase login を行う
 *
 * 環境変数:
 *   QA_SMOKE_BASE_URL    対象 frontend (default: https://app.salesanchor.jp)
 *   QA_SMOKE_API_URL     対象 API     (default: https://api.salesanchor.jp)
 *   CI                   CI 上は retries=1 + traces を毎回保存
 *
 * 関連:
 *   docs/adr/ADR-038-qa-smoke-suite.md
 *   tests/qa-smoke/fixtures/qa-tenant-creds.ts
 *   tests/qa-smoke/utils/real-backend.ts
 *   tests/qa-smoke/utils/db-assert.ts
 *   .github/workflows/qa-smoke.yml
 */

import { defineConfig, devices } from "@playwright/test";

const BASE_URL = process.env.QA_SMOKE_BASE_URL || "https://app.salesanchor.jp";

export default defineConfig({
  testDir: ".",
  // scene 01〜08 は順序依存ではないが、共有 backend を叩くため worker=1 で順次実行
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  // 1 test あたり 2 分上限。ADR-038 の所要時間（5〜20 分/シーン、3〜5 tests/シーン）
  // から逆算: 最長シーン 20 分 ÷ 5 tests = 4 分/test。余裕を持ち 2 分を基準値とする。
  // VPS 2GB 制約 (ADR-038 L95) は worker 数・同時実行数の制限であり 1 test 単位のタイムアウトではない。
  timeout: 120_000,
  expect: { timeout: 10_000 },

  reporter: process.env.CI
    ? [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]]
    : [["list"]],

  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    // 実 backend を相手にするので User-Agent で smoke を識別可能にする
    extraHTTPHeaders: {
      "X-QA-Smoke": "adr-038",
    },
  },

  projects: [
    {
      name: "chromium-qa-smoke",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  // mock e2e と違って Vite dev server は起動しない — 本番 frontend を直接叩く
});
