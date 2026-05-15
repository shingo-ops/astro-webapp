/**
 * ADR-038 / QA Smoke Suite — 実 backend 向け Playwright ヘルパー
 *
 * frontend/tests-e2e/utils/auth.ts は mock を仕込んでいたが、本ファイルは
 * **実際の Firebase に対して login する**。テスト先頭で `login(page, 'admin')`
 * を呼べば、その後の page.goto('/') で Dashboard が描画される。
 *
 * 設計:
 *   - LoginPage の email/password 入力 + ログイン clcik を実行
 *   - 認証後の遷移先 (/ もしくは /dashboard) を baseURL からの相対で待つ
 *   - 失敗時はスクリーンショットを残し、明確な Error を投げる
 *   - console.error の蓄積機能 (scene-02 等で件数 assert に使う)
 */

import type { Page, BrowserContext } from "@playwright/test";
import { expect } from "@playwright/test";
import { QA_USERS } from "../fixtures/qa-tenant-creds";

export type QaRole = "admin" | "staff" | "viewer";

/**
 * Real-backend login。LoginPage を操作して Firebase 経由で signIn する。
 *
 * 注意: frontend の LoginPage UI が「メールアドレス」「パスワード」「ログイン」
 * というラベルを使う前提 (scene1-dashboard.spec.ts と同じ)。
 */
export async function login(page: Page, role: QaRole): Promise<void> {
  const cred = QA_USERS[role];
  await page.goto("/login", { waitUntil: "domcontentloaded" });

  await page.getByLabel("メールアドレス").fill(cred.email);
  await page.getByLabel("パスワード").fill(cred.password);
  await page.getByRole("button", { name: "ログイン" }).click();

  // ログイン成功後は `/` (Dashboard) に遷移する想定。最大 navigationTimeout 待機。
  await page.waitForURL((u) => u.pathname === "/" || u.pathname === "/dashboard", {
    timeout: 30_000,
  });

  // 念のため Dashboard 見出しの描画も待つ
  await expect(page.getByRole("heading", { name: /ダッシュボード|Dashboard/i })).toBeVisible({
    timeout: 20_000,
  });
}

/**
 * page.context() レベルで console.error を蓄積する。
 * scene-02 で「console.error 0 件」を assert するための補助。
 */
export function collectConsoleErrors(page: Page): { errors: string[] } {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      errors.push(msg.text());
    }
  });
  page.on("pageerror", (err) => {
    errors.push(String(err));
  });
  return { errors };
}

/**
 * frontend で Logout する。context をまたいで違う role でログインし直したい時に使う。
 */
export async function logout(page: Page): Promise<void> {
  // 共通レイアウト右上の「ログアウト」ボタン or リンクを期待。
  // 実装が UI 変更で変わったら locator を更新する。
  const logoutTrigger = page.getByRole("button", { name: /ログアウト|Logout/i });
  if (await logoutTrigger.isVisible().catch(() => false)) {
    await logoutTrigger.click();
    await page.waitForURL((u) => u.pathname.includes("/login"), { timeout: 15_000 });
  }
}

/**
 * 新しい page でフレッシュな login を実行するためのファクトリ。
 * 同じ context で複数 role を切り替える時のパターン。
 */
export async function freshPageWithLogin(
  context: BrowserContext,
  role: QaRole,
): Promise<Page> {
  await context.clearCookies();
  const page = await context.newPage();
  await login(page, role);
  return page;
}
