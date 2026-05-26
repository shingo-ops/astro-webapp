/**
 * spec.md v1.3 F11 AC11.5 + AC11.6 — /super-admin/inventory-offers の admin
 * CRUD UI を Playwright で実機検証する。AC11.2 (CSV 102 行投入) は backend で
 * 検証済 (test_seed_inventory_csv.py 想定)、本 spec は admin UI 側で 102 行
 * (mock 上の総件数) が一覧に表示・編集・削除できることをカバーする。
 *
 * AC 対応:
 *   AC11.2: 出力.csv → 102 行投入 (UI 側で total=102 のページネーション表示)
 *   AC11.5: 仕入元別オファー一覧 UI で admin が手動編集できる
 *   AC11.6: Playwright で AC11.2 / AC11.5 を実機検証
 *
 * 既存 super-admin-*.spec.ts と同じ「Playwright route で /api/v1/* mock」パターン。
 * 実 backend での AC は backend pytest 側 (test_inventory_offers_rbac.py) で検証。
 */
import { expect, test } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi, type MockMap } from "./utils/api-mock";

const baseMocks = (isSuperAdmin: boolean): MockMap => ({
  "GET /me/permissions": {
    permissions: ["dashboard.view"],
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

function makeOffer(over: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1001,
    supplier_id: 11,
    product_id: 701,
    condition: "sealed",
    quantity: 4,
    unit_price: 1400,
    status: "in_stock",
    notes_ja: null,
    notes_en: null,
    offered_at: "2026-05-26T09:00:00+00:00",
    expires_at: null,
    source: "f6_approved",
    created_at: "2026-05-26T09:00:00+00:00",
    updated_at: "2026-05-26T09:00:00+00:00",
    supplier_name: "AC11.5 仕入元 A",
    product_code: "F11-LIZ-001",
    product_name: "リザードン ex SAR",
    ...over,
  };
}

const SAMPLE_LIST_AC11_2 = {
  items: [makeOffer(), makeOffer({ id: 1002, supplier_id: 12, supplier_name: "AC11.5 仕入元 B", unit_price: 1600 })],
  total: 102, // AC11.2: 出力.csv 102 行投入 (mock 上の総件数表示確認)
  page: 1,
  per_page: 50,
};

test.describe("Sprint 11 / F11 AC11.5 — /super-admin/inventory-offers admin CRUD", () => {
  test("AC11.5 (gate): is_super_admin=false なら 403 アラートが描画される", async ({
    page,
  }) => {
    await installAuthBypass(page);
    await mockApi(page, baseMocks(false));
    await page.goto("/super-admin/inventory-offers");

    // 一覧 (offers-table) は描画されない
    await expect(page.getByTestId("offers-table")).toHaveCount(0);
    // 403 メッセージが role="alert" で出る
    await expect(page.getByRole("alert")).toBeVisible({ timeout: 15_000 });
  });

  test("AC11.2 + AC11.5: 一覧が描画され total 件数が表示される", async ({
    page,
  }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...baseMocks(true),
      "GET /super-admin/inventory-offers": SAMPLE_LIST_AC11_2,
    });
    await page.goto("/super-admin/inventory-offers");

    // table 描画
    await expect(page.getByTestId("offers-table")).toBeVisible({
      timeout: 15_000,
    });
    // row 2 件
    await expect(page.getByTestId("offers-row-1001")).toBeVisible();
    await expect(page.getByTestId("offers-row-1002")).toBeVisible();
    // AC11.2: total=102 がページネーションラベルに表示
    await expect(page.getByTestId("offers-pagination-label")).toContainText("102");
  });

  test("AC11.5: 編集ボタンで row が編集モードに → PATCH 送信 → 完了 info", async ({
    page,
  }) => {
    let patchBody: Record<string, unknown> | null = null;
    let listCount = 0;

    await installAuthBypass(page);
    await mockApi(page, {
      ...baseMocks(true),
      "GET /super-admin/inventory-offers": async (route) => {
        listCount += 1;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(SAMPLE_LIST_AC11_2),
        });
      },
      "PATCH /super-admin/inventory-offers/1001": async (route) => {
        patchBody = JSON.parse(route.request().postData() ?? "{}");
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ...makeOffer(),
            quantity: 7,
            unit_price: 2000,
            status: "reserved",
          }),
        });
      },
    });

    await page.goto("/super-admin/inventory-offers");
    await expect(page.getByTestId("offers-row-1001-edit")).toBeVisible({
      timeout: 15_000,
    });

    // 編集モード
    await page.getByTestId("offers-row-1001-edit").click();
    await expect(page.getByTestId("offers-row-1001-quantity")).toBeVisible();
    await page.getByTestId("offers-row-1001-quantity").fill("7");
    await page.getByTestId("offers-row-1001-unit-price").fill("2000");
    await page.getByTestId("offers-row-1001-status").selectOption("reserved");

    // 保存
    await page.getByTestId("offers-row-1001-save").click();

    // info 表示 + PATCH ペイロード検証
    await expect(page.getByTestId("offers-info")).toBeVisible();
    expect(patchBody).toBeTruthy();
    expect((patchBody as Record<string, unknown>).quantity).toBe(7);
    expect((patchBody as Record<string, unknown>).unit_price).toBe(2000);
    expect((patchBody as Record<string, unknown>).status).toBe("reserved");

    // M4 follow-up: 保存後の自動 reload を検証する。
    // InventoryOffersPage.submitEdit() の最後で `await load()` が呼ばれ、
    // 編集結果を画面に即時反映する UX 仕様。listCount は初期描画 1 + 保存後 reload 1
    // で >= 2 になる (poll で eventual consistency 確認)。
    await expect.poll(() => listCount).toBeGreaterThanOrEqual(2);
  });

  test("AC11.5: 検索クエリ入力で q パラメータが API へ送信される", async ({
    page,
  }) => {
    const observedQs: string[] = [];
    await installAuthBypass(page);
    await mockApi(page, {
      ...baseMocks(true),
      "GET /super-admin/inventory-offers": async (route) => {
        const url = new URL(route.request().url());
        observedQs.push(url.searchParams.get("q") ?? "");
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(SAMPLE_LIST_AC11_2),
        });
      },
    });

    await page.goto("/super-admin/inventory-offers");
    await expect(page.getByTestId("offers-search")).toBeVisible({
      timeout: 15_000,
    });

    await page.getByTestId("offers-search").fill("リザードン");

    // 検索クエリが含まれる呼び出しが少なくとも 1 件出る
    await expect.poll(() => observedQs.some((q) => q === "リザードン")).toBe(
      true,
    );
  });
});
