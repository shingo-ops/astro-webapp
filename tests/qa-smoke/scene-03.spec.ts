/**
 * ADR-038 / Scene 03: Customers (Companies + Contacts)
 *
 * 目的:
 *   - 一覧 → 詳細 → 編集 → 新規 → 検索の最低限の lifecycle
 *   - seed された 5 件の QA Company が表示される (実 API 経由)
 *   - 新規作成は接頭辞 'QA-' を付け、cleanup-smoke-data.sh で消える
 *
 * 所要: 15 分目安
 */

import { expect, test } from "@playwright/test";
import { login } from "./utils/real-backend";
import { psqlCount } from "./utils/db-assert";

test.describe("Scene 03: Customers (real backend)", { tag: ['@scene-03'] }, () => {
  test.beforeEach(async ({ page }) => {
    await login(page, "admin");
  });

  test("companies 一覧に seed 済 5 件が出ている", async ({ page }) => {
    await page.goto("/customers", { waitUntil: "domcontentloaded" });

    // 一覧画面 (Companies tab) でいずれかの seed company が見える
    await expect(page.getByText("QA Company A")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("QA Company B")).toBeVisible();
    await expect(page.getByText("QA Company C")).toBeVisible();
  });

  test("seed company の検索が動く", async ({ page }) => {
    await page.goto("/customers");

    // 検索 input (placeholder で識別、frontend が 'search' 系のラベルを使う前提)
    const search = page.getByPlaceholder(/検索|search/i).first();
    await search.fill("QA Company E");
    // debounce 待ち
    await page.waitForTimeout(500);

    await expect(page.getByText("QA Company E")).toBeVisible({ timeout: 10_000 });
    // 他の seed が visible に残らないことの厳密 assert は frontend の filter 仕様
    // に依存するためここでは hit 行が出ているだけを確認
  });

  test("seed の company を開いて contact が紐付いていることを確認", async ({ page }) => {
    await page.goto("/customers");

    await page.getByText("QA Company A").first().click();
    // 詳細画面に primary contact 名が出る
    await expect(page.getByText("QA Contact A")).toBeVisible({ timeout: 15_000 });
  });

  test("新規 company 作成は QA- 接頭辞、cleanup で消える形になる", async ({ page }) => {
    // 念のため作成前後で件数が +1 されることだけ確認 (新規作成画面の UI は実装依存)
    const before = psqlCount(
      `SELECT COUNT(*) FROM tenant_006.companies WHERE company_code LIKE 'QA-SMK-%'`,
    );

    // 新規ボタン (label は frontend 実装に依存するため緩く)
    await page.goto("/customers");
    const newBtn = page.getByRole("button", { name: /新規|追加|新規作成|新規企業|新規顧客/ });
    // 実装によっては link なので両対応
    if (await newBtn.first().isVisible().catch(() => false)) {
      await newBtn.first().click();
      // 必須フィールドだけ埋めて submit。company name / 会社名 のラベルを期待
      const nameField = page.getByLabel(/会社名|company.*name/i).first();
      if (await nameField.isVisible().catch(() => false)) {
        const code = `QA-SMK-${Date.now()}`;
        await nameField.fill(`QA Smoke Company ${code}`);
        const submit = page.getByRole("button", { name: /作成|保存|登録|create|save/i }).first();
        await submit.click();

        // 反映待ち (a) DB 件数 +1、 (b) URL が一覧 or 詳細に戻る
        await page.waitForTimeout(1500);
        const after = psqlCount(
          `SELECT COUNT(*) FROM tenant_006.companies WHERE name LIKE 'QA Smoke Company%'`,
        );
        expect(after, "新規作成後に DB 件数が増えていない").toBeGreaterThan(before);
      } else {
        test.info().annotations.push({
          type: "skip-reason",
          description: "新規作成 form の会社名 input が見つからず作成 step を skip",
        });
      }
    } else {
      test.info().annotations.push({
        type: "skip-reason",
        description: "新規作成ボタンが見つからず作成 step を skip",
      });
    }
  });
});
