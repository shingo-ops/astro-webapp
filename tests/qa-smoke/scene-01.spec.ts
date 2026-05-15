/**
 * ADR-038 / Scene 01: Auth & Roles
 *
 * 目的:
 *   - 3 ユーザー (admin / staff / viewer) で実 Firebase login が通る
 *   - 各ロールで Dashboard 描画 + 主要ナビが見える
 *   - viewer は管理メニューが出ない (権限切替の最小チェック)
 *
 * 所要: 10 分目安 (ADR-038 表)
 */

import { expect, test } from "@playwright/test";
import { login, logout } from "./utils/real-backend";
import { QA_USERS } from "./fixtures/qa-tenant-creds";

test.describe("Scene 01: Auth & Roles (real backend)", () => {
  for (const role of ["admin", "staff", "viewer"] as const) {
    test(`${role} が login して Dashboard を見られる`, async ({ page }) => {
      await login(page, role);

      await expect(page.getByRole("heading", { name: /ダッシュボード|Dashboard/i }))
        .toBeVisible({ timeout: 20_000 });

      // メインナビは admin/staff/viewer 全員に出る
      const nav = page.locator("nav.mainnav");
      await expect(nav).toBeVisible();
      await expect(nav.getByRole("link", { name: /ダッシュボード|Dashboard/i })).toBeVisible();
    });
  }

  test("viewer は管理 (admin) メニューが表示されない", async ({ page }) => {
    await login(page, "viewer");
    const nav = page.locator("nav.mainnav");
    // viewer ロール = '管理' / 'システム管理' トリガが出ない想定
    // toBeHidden ではなく count==0 で確認 (locator が見つからなくても通過)
    const adminTrigger = nav.getByRole("button", { name: /管理|Admin/i });
    const count = await adminTrigger.count();
    expect(count, "viewer に管理メニューが見えています").toBe(0);
  });

  test("間違ったパスワードでは login 失敗 (Firebase auth が生きていることの確認)", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("メールアドレス").fill(QA_USERS.admin.email);
    await page.getByLabel("パスワード").fill("definitely-wrong-password-for-smoke");
    await page.getByRole("button", { name: "ログイン" }).click();

    // エラー表示を待つ — 文言は frontend 実装に依存するため緩く正規表現で
    await expect(page.getByText(/エラー|失敗|invalid|incorrect|無効/i))
      .toBeVisible({ timeout: 15_000 });
    // login 後の Dashboard 遷移が起きていないこと
    await expect(page).not.toHaveURL(/\/$/);
  });

  test.afterEach(async ({ page }) => {
    await logout(page).catch(() => {/* best-effort */});
  });
});
