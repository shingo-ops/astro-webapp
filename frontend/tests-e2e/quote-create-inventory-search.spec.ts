/**
 * Sprint 7 (F7) — QuoteCreatePage に組み込まれた InventorySearchBar の UI smoke。
 *
 * AC 対応:
 *   AC7.4: 候補選択 → quote_items に標準名 + 標準 unit_price が乗る (UI 経路)
 *   AC7.5: 在庫 0 商品はグレーアウト、選択時 warning メッセージ表示
 *   AC7.7: i18n placeholder / AND/OR ラベル / バッジ がすべて t() 経由 (mock 上の表示確認)
 *   AC7.8: AND/OR トグルが UI 操作可能
 *
 * Note:
 *   - 本 spec は `/api/v1/inventory/search` を Playwright route で mock 化する。
 *   - 実 PG 横断 / ranking / pg_trgm の SLO 検証は backend/tests/test_inventory_search*.py で実施。
 *   - QuoteCreatePage への組み込み骨格と UI 動作 (キーボード操作 / トグル / 警告) を確認する。
 */

import { expect, test } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi } from "./utils/api-mock";
import { commonMocks } from "./utils/common-mocks";

const INVENTORY_RESPONSE = {
  query: "リザードン",
  op: "or",
  total: 2,
  masked: false,
  candidates: [
    {
      product_id: 101,
      name: "リザードン ex SAR (in-stock)",
      name_en: "Charizard ex SAR",
      product_code: "S7-LIZ-001",
      expansion_code: "SV1a",
      card_number: "SV1a-001",
      jan_code: null,
      unit_price: 1500,
      stock_quantity: 5,
      supplier_default_id: 1,
      supplier_name: "Sample Supplier",
      image_url: null,
      matched_via: "products_name",
      score: 13,
    },
    {
      product_id: 102,
      name: "リザードン ex SAR (zero stock)",
      name_en: "Charizard ex SAR (out)",
      product_code: "S7-LIZ-002",
      expansion_code: "SV1a",
      card_number: "SV1a-002",
      jan_code: null,
      unit_price: 1200,
      stock_quantity: 0,
      supplier_default_id: 1,
      supplier_name: "Sample Supplier",
      image_url: null,
      matched_via: "products_name",
      score: 1013,
    },
  ],
};

const EMPTY_RESPONSE = { query: "", op: "or", total: 0, masked: false, candidates: [] };

async function setupQuoteCreatePageMocks(page: import("@playwright/test").Page) {
  await installAuthBypass(page);
  await mockApi(page, {
    ...commonMocks(),
    "GET /products": [],
    "GET /companies": [],
    "GET /contacts": [],
    // 検索 q を含む URL は wildcard で受ける必要があるため key を method+path のみで対応:
    "GET /inventory/search": (route) => {
      const url = new URL(route.request().url());
      const q = url.searchParams.get("q") || "";
      if (!q.trim()) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(EMPTY_RESPONSE),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(INVENTORY_RESPONSE),
      });
    },
  });
}

test.describe("Sprint 7 / F7 — QuoteCreatePage InventorySearchBar UI smoke", () => {
  test("検索バーが描画され placeholder が i18n 経由", async ({ page }) => {
    await setupQuoteCreatePageMocks(page);
    await page.goto("/quotes/new");

    const input = page.getByTestId("quote-inventory-search-0-input");
    await expect(input).toBeVisible({ timeout: 20_000 });
    // placeholder は ja.json の inventory.search.placeholder を表示するはず
    const placeholder = await input.getAttribute("placeholder");
    expect(placeholder).toBeTruthy();
    expect(placeholder!.length).toBeGreaterThan(0);
  });

  test("AC7.7 / AC7.8: AND/OR トグルが UI 上でクリック可能", async ({ page }) => {
    await setupQuoteCreatePageMocks(page);
    await page.goto("/quotes/new");

    const orBtn = page.getByTestId("quote-inventory-search-0-op-or");
    const andBtn = page.getByTestId("quote-inventory-search-0-op-and");
    await expect(orBtn).toBeVisible({ timeout: 20_000 });
    await expect(andBtn).toBeVisible();
    await expect(orBtn).toHaveAttribute("aria-pressed", "true");
    await andBtn.click();
    await expect(andBtn).toHaveAttribute("aria-pressed", "true");
    await expect(orBtn).toHaveAttribute("aria-pressed", "false");
  });

  test("AC7.4 / AC7.5: 候補選択 → 行の name input が標準名で埋まり、在庫 0 行は警告が出る", async ({ page }) => {
    await setupQuoteCreatePageMocks(page);
    await page.goto("/quotes/new");

    const input = page.getByTestId("quote-inventory-search-0-input");
    await input.fill("リザードン");
    // debounce 250ms
    await page.waitForTimeout(400);

    // 候補リスト
    const result0 = page.getByTestId("quote-inventory-search-0-result-0");
    await expect(result0).toBeVisible();
    const result0Name = page.getByTestId("quote-inventory-search-0-result-0-name");
    await expect(result0Name).toContainText("リザードン ex SAR (in-stock)");

    // 在庫 0 の row は data-zero-stock=true
    const result1 = page.getByTestId("quote-inventory-search-0-result-1");
    await expect(result1).toHaveAttribute("data-zero-stock", "true");

    // in-stock を選択
    await result0.click();

    // AC7.4: 行の name 列に標準名が入る
    const nameInput = page.getByTestId("quote-item-row-0-name");
    await expect(nameInput).toHaveValue("リザードン ex SAR (in-stock)");

    // 再度 search → zero-stock を選択
    await input.fill("リザードン");
    await page.waitForTimeout(400);
    const result1b = page.getByTestId("quote-inventory-search-0-result-1");
    await result1b.click();

    // AC7.5: zero-stock warning が QuoteCreatePage 行内に表示される
    const warning = page.getByTestId("quote-item-row-0-zero-stock-warning");
    await expect(warning).toBeVisible();
  });
});
