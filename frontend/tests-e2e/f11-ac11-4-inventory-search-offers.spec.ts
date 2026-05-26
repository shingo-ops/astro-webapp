/**
 * spec.md v1.3 F11 AC11.4 + AC11.6 — F7 在庫検索結果に仕入元現在オファー
 * (`inventory_offers`) が表示されることを Playwright で確認する。
 *
 * AC 対応:
 *   AC11.4: F7 検索結果に inventory.quantity / unit_price が表示される
 *   AC11.6: Playwright で AC11.4 を実機検証
 *
 * 既存 quote-create-inventory-search.spec.ts と同じく
 * `/api/v1/inventory/search` を route で mock 化、UI が
 * candidates[].inventory_offers[] を読み取って描画するかを検証する。
 *
 * 実 PG での JOIN ロジックは backend/tests/test_inventory_search*.py で別途検証。
 */
import { expect, test } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi } from "./utils/api-mock";
import { commonMocks } from "./utils/common-mocks";

const RESPONSE_WITH_OFFERS = {
  query: "リザードン",
  op: "or",
  total: 1,
  masked: false,
  candidates: [
    {
      product_id: 201,
      name: "リザードン ex SAR (offers)",
      name_en: "Charizard ex SAR (offers)",
      product_code: "F11-LIZ-001",
      expansion_code: "SV1a",
      card_number: "SV1a-201",
      jan_code: null,
      unit_price: 1500,
      stock_quantity: 5,
      supplier_default_id: 1,
      supplier_name: "Default Supplier",
      image_url: null,
      matched_via: "products_name",
      score: 13,
      inventory_offers: [
        {
          supplier_id: 11,
          supplier_name: "AC11.4 仕入元 A",
          condition: "sealed",
          quantity: 4,
          unit_price: 1400,
          status: "in_stock",
        },
        {
          supplier_id: 12,
          supplier_name: "AC11.4 仕入元 B",
          condition: "sealed",
          quantity: 2,
          unit_price: 1600,
          status: "in_stock",
        },
        {
          supplier_id: 13,
          supplier_name: "AC11.4 仕入元 C",
          condition: "sealed",
          quantity: 1,
          unit_price: 1700,
          status: "in_stock",
        },
        {
          supplier_id: 14,
          supplier_name: "AC11.4 仕入元 D",
          condition: "sealed",
          quantity: 3,
          unit_price: 1800,
          status: "in_stock",
        },
      ],
    },
  ],
};

const RESPONSE_MASKED = {
  query: "リザードン",
  op: "or",
  total: 1,
  masked: true,
  candidates: [
    {
      product_id: 202,
      name: "リザードン ex SAR (masked)",
      name_en: "Charizard ex SAR (masked)",
      product_code: "F11-LIZ-002",
      expansion_code: "SV1a",
      card_number: "SV1a-202",
      jan_code: null,
      unit_price: 1500,
      stock_quantity: null,
      supplier_default_id: 1,
      supplier_name: "Default Supplier",
      image_url: null,
      matched_via: "products_name",
      score: 13,
      inventory_offers: [
        {
          supplier_id: 21,
          supplier_name: "AC11.4 仕入元 X",
          condition: "sealed",
          quantity: null,
          unit_price: null,
          status: "in_stock",
        },
      ],
    },
  ],
};

const EMPTY_RESPONSE = {
  query: "",
  op: "or",
  total: 0,
  masked: false,
  candidates: [],
};

async function setupMocks(
  page: import("@playwright/test").Page,
  response: typeof RESPONSE_WITH_OFFERS | typeof RESPONSE_MASKED,
) {
  await installAuthBypass(page);
  await mockApi(page, {
    ...commonMocks(),
    "GET /products": [],
    "GET /companies": [],
    "GET /contacts": [],
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
        body: JSON.stringify(response),
      });
    },
  });
}

test.describe("Sprint 11 / F11 AC11.4 — InventorySearchBar offers display", () => {
  test("AC11.4: 検索結果に inventory_offers が compact 表示される (最大 3 件 + more)", async ({
    page,
  }) => {
    await setupMocks(page, RESPONSE_WITH_OFFERS);
    await page.goto("/quotes/new");

    const input = page.getByTestId("quote-inventory-search-0-input");
    await expect(input).toBeVisible({ timeout: 20_000 });
    await input.fill("リザードン");

    // debounce (250ms) 経過後、最初の offer 行が描画されるまで直接待つ
    // (Playwright anti-pattern を避けるため waitForTimeout を使用しない)
    const offer0 = page.getByTestId("quote-inventory-search-0-result-0-offer-0");
    await expect(offer0).toBeVisible({ timeout: 5_000 });

    const offersBlock = page.getByTestId(
      "quote-inventory-search-0-result-0-offers",
    );
    await expect(offersBlock).toBeVisible();

    // 最大 3 件まで個別 offer が描画 (4 件中)
    await expect(
      page.getByTestId("quote-inventory-search-0-result-0-offer-1"),
    ).toBeVisible();
    await expect(
      page.getByTestId("quote-inventory-search-0-result-0-offer-2"),
    ).toBeVisible();
    // 4 件目は折り畳まれて出ない
    await expect(
      page.getByTestId("quote-inventory-search-0-result-0-offer-3"),
    ).toHaveCount(0);

    // 最初の仕入元名 + condition + qty + unit_price が表示
    await expect(offer0).toContainText("AC11.4 仕入元 A");
    await expect(offer0).toContainText("sealed");
    await expect(offer0).toContainText("1,400");

    // "他 1 件" の more 表示が出る (offersMore i18n: "他 {{extra}} 件")
    // M1 follow-up: "1" だけだと unit_price 1,400 等にも match して assertion が弱いため、
    // i18n 翻訳後の完全文字列で直接 assert する
    await expect(offersBlock).toContainText("他 1 件");
  });

  test("AC11.4: inventory_offers[].quantity=null / unit_price=null は *** マスク表示", async ({
    page,
  }) => {
    // M2 follow-up: 元の "masked=true" という test 名は誤解を招いていた。
    // 実装 (InventorySearchBar.tsx:474-480) は response.masked フラグではなく、
    // offer 個別の quantity=null / unit_price=null を *** に置換する。
    // response.masked は別の masked-indicator バナー描画にのみ使われる。
    await setupMocks(page, RESPONSE_MASKED);
    await page.goto("/quotes/new");

    const input = page.getByTestId("quote-inventory-search-0-input");
    await expect(input).toBeVisible({ timeout: 20_000 });
    await input.fill("リザードン");

    const offer0 = page.getByTestId("quote-inventory-search-0-result-0-offer-0");
    await expect(offer0).toBeVisible({ timeout: 5_000 });
    await expect(offer0).toContainText("***");

    // M2: 加えて、response.masked=true で masked-indicator バナーも出る
    await expect(
      page.getByTestId("quote-inventory-search-0-masked-indicator"),
    ).toBeVisible();
  });
});
