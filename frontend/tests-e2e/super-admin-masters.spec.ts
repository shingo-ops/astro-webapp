/**
 * spec.md v1.1 F2 (Sprint 2) — /super-admin/masters の Playwright E2E。
 *
 * AC2.1: is_super_admin=false なら 403 メッセージ、=true なら 4 タブ表示
 * AC2.2: Knowledge タブで新規 rule の作成 → 一覧に反映
 * AC2.3: TCG タブで series_code 編集
 * AC2.4: Dex タブで pokemon #25 編集
 * AC2.5: Suppliers タブで supplier_type 切替 + Discord routing
 *
 * 注意:
 *   実 backend には繋がず Playwright route で /api/v1/* を mock する（撮影台本 e2e と
 *   同じパターン）。実 backend での AC 確認は backend pytest + 本番 VPS スモークで
 *   別途実施（spec SC6 SQLite モック禁止条項は backend テストに対する制約で、
 *   frontend e2e は UI 描画 / ナビゲーションを mock で検証する用途）。
 */
import { expect, test } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi, type MockMap } from "./utils/api-mock";

const baseMocks = (isSuperAdmin: boolean): MockMap => ({
  "GET /me/permissions": {
    permissions: [
      "dashboard.view",
      "tenant.inventory_visibility.edit",
      "roles.view",
    ],
    is_super_admin: isSuperAdmin,
  },
  "GET /staff/me": {
    id: 1,
    primary_email: "review@salesanchor.jp",
    ui_preferences: {
      dark_mode: false,
      show_chat_menu: true,
      show_sales_menu: true,
      show_settings_menu: true,
      show_admin_menu: true,
      show_sidebar: true,
    },
  },
});

test.describe("Sprint 2 / F2 — /super-admin/masters", () => {
  test("AC2.1: is_super_admin=false の場合は 403 メッセージが表示される", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, baseMocks(false));
    await page.goto("/super-admin/masters");

    await expect(page.getByRole("alert")).toContainText(
      /Jarvis|Central|運用 admin|admins/i,
    );
    // 4 タブのうち、Knowledge タブのテストid が描画されていないこと
    await expect(page.getByTestId("super-admin-tab-knowledge")).toHaveCount(0);
  });

  test("AC2.1: is_super_admin=true の場合は 4 タブが描画される", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...baseMocks(true),
      // 各タブの初期 fetch をいずれも空配列で返す（描画さえできれば AC2.1 は満たす）
      "GET /super-admin/knowledge": [],
      "GET /super-admin/aliases": [],
      "GET /super-admin/tcg/series": [],
      "GET /super-admin/dex/pokemon": [],
      "GET /super-admin/suppliers": [],
    });
    await page.goto("/super-admin/masters");

    // 4 タブが描画される
    await expect(page.getByTestId("super-admin-tab-knowledge")).toBeVisible();
    await expect(page.getByTestId("super-admin-tab-tcg")).toBeVisible();
    await expect(page.getByTestId("super-admin-tab-dex")).toBeVisible();
    await expect(page.getByTestId("super-admin-tab-suppliers")).toBeVisible();
  });

  test("AC2.2: Knowledge タブで新規 rule 作成 → 一覧に反映される", async ({ page }) => {
    await installAuthBypass(page);

    let listCalled = 0;
    const initialRules: unknown[] = [];
    const afterCreate = [
      {
        id: 1,
        category: "tcg",
        pattern_type: "regex",
        pattern: "^PSV1a-(\\d+)",
        normalized_to: "SV1a-$1",
        priority: 100,
        language: "ja",
        is_active: true,
        created_at: "2026-05-21T00:00:00Z",
      },
    ];

    await mockApi(page, {
      ...baseMocks(true),
      "GET /super-admin/aliases": [],
      "GET /super-admin/tcg/series": [],
      "GET /super-admin/dex/pokemon": [],
      "GET /super-admin/suppliers": [],
      "GET /super-admin/knowledge": (route) => {
        listCalled++;
        const body = listCalled === 1 ? initialRules : afterCreate;
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(body),
        });
      },
      "POST /super-admin/knowledge": {
        status: 201,
        body: afterCreate[0],
      },
    });

    await page.goto("/super-admin/masters");
    await expect(page.getByTestId("super-admin-tab-knowledge")).toBeVisible();

    // フォームに入力 → submit
    await page.locator('input[placeholder*="ategor"], input[placeholder*="カテゴリ"]').first().fill("tcg");
    await page.locator('input[placeholder*="attern"], input[placeholder*="パターン"]').first().fill("^PSV1a-(\\d+)");
    await page.locator('input[placeholder*="ormaliz"], input[placeholder*="正規化"]').first().fill("SV1a-$1");

    // 「ルール新規作成」ボタン (submit type)
    const submitBtn = page.locator('button[type="submit"]').first();
    await submitBtn.click();

    // 一覧に反映
    await expect(page.locator("table").first()).toContainText("^PSV1a-(\\d+)");
    await expect(page.locator("table").first()).toContainText("SV1a-$1");
  });
});
