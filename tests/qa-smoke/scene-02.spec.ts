/**
 * ADR-038 / Scene 02: Dashboard
 *
 * 目的:
 *   - Dashboard で KPI カード (顧客数 / コンバージョン率 / 成約金額) が描画される
 *   - ページ全体で console.error が 0 件 (実 API を叩いて壊れない)
 *
 * 所要: 5 分目安
 */

import { expect, test } from "@playwright/test";
import { login } from "./utils/real-backend";
import { collectConsoleErrors } from "./utils/real-backend";

test.describe("Scene 02: Dashboard (real backend)", () => {
  test("Dashboard KPI が描画され、console.error が 0 件", async ({ page }) => {
    const { errors } = collectConsoleErrors(page);

    await login(page, "admin");

    // 主要 KPI 3 種が見える
    await expect(page.getByText("顧客数")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("コンバージョン率")).toBeVisible();
    await expect(page.getByText("成約金額")).toBeVisible();

    // 初期描画後にネットワーク idle まで待ってから error 件数を確認
    await page.waitForLoadState("networkidle", { timeout: 20_000 });

    // 既知の Firebase auth refresh 由来 warning は許容するため、grep で絞り込む
    const fatal = errors.filter(
      (e) =>
        !/Firebase.*deprecated/i.test(e) &&
        !/Failed to load resource: net::ERR_BLOCKED_BY_CLIENT/i.test(e),
    );
    expect(fatal, `console.error が出ています:\n${fatal.join("\n")}`).toEqual([]);
  });
});
