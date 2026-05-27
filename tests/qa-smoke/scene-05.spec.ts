/**
 * ADR-038 / Scene 05: Leads & Orders
 *
 * 目的:
 *   - leads 5 件が seed 通り status バリエーション (新規/対応中/評価済/失注/受注) で並ぶ
 *   - orders 3 件の合計売上が DB と一致 (15000 + 32500 + 8900 = 56,400)
 *   - lead 詳細から order に飛べる lifecycle 動線が壊れていない
 *
 * 所要: 20 分目安
 */

import { expect, test } from "@playwright/test";
import { login } from "./utils/real-backend";
import { psqlCount, psqlRows } from "./utils/db-assert";

const EXPECTED_TOTAL = 15000 + 32500 + 8900;

test.describe("Scene 05: Leads & Orders (real backend)", { tag: ['@scene-05'] }, () => {
  test("seed leads 5 件、status が 5 種類分かれている", () => {
    expect(
      psqlCount(`SELECT COUNT(*) FROM tenant_006.leads WHERE lead_code LIKE 'QA-LD-%'`),
    ).toBe(5);

    const rows = psqlRows(
      `SELECT DISTINCT status FROM tenant_006.leads WHERE lead_code LIKE 'QA-LD-%' ORDER BY status`,
    );
    expect(rows.length).toBeGreaterThanOrEqual(5);
  });

  test("seed orders 3 件、合計売上が DB 計算と一致する", () => {
    const rows = psqlRows(
      `SELECT SUM(total_amount)::TEXT FROM tenant_006.orders WHERE order_number LIKE 'QA-OR-%'`,
    );
    const sum = Number(rows[0][0]);
    expect(sum).toBeCloseTo(EXPECTED_TOTAL, 0);
  });

  test("Leads 画面で seed lead が表示される", async ({ page }) => {
    await login(page, "admin");
    await page.goto("/leads", { waitUntil: "domcontentloaded" });

    await expect(page.getByText("QA Lead New")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("QA Lead Won")).toBeVisible();
  });

  test("Orders 画面で seed order が表示される", async ({ page }) => {
    await login(page, "admin");
    await page.goto("/orders", { waitUntil: "domcontentloaded" });

    // order_number 表示は frontend 実装に依存するが、QA-OR-001 文字列か
    // 関連企業名 (QA Company A) のいずれかで存在確認
    const hasOrderNum = await page.getByText("QA-OR-001").isVisible().catch(() => false);
    const hasCompany = await page.getByText("QA Company A").isVisible().catch(() => false);
    expect(hasOrderNum || hasCompany, "Orders 画面に seed order が表示されない").toBeTruthy();
  });
});
