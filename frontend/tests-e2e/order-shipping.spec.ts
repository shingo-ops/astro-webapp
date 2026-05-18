/**
 * ADR-021 Phase 3 / Sprint 3 — 発送情報 MVP の E2E テスト。
 *
 * 検証範囲（spec.md AC-3.7）:
 *   - 受注一覧から「発送編集」を開いて発送情報フォームが表示される
 *   - 受取人 / 住所 / 追跡番号を入力 → 保存 → 一覧の追跡番号列が更新
 *   - 既存発送情報は PATCH、未登録は POST に振り分けられる（404 → 新規）
 *   - eLogi CSV ダウンロードボタンが API 呼び出しを発火する
 *   - 既存 Sprint 1 / 2 の検索 / ソート / 売上編集が壊れない（同じ data-testid 維持）
 *
 * Backend は API mock 経由で固定（ADR-019/020 の英語 UI 影響を受けない）。
 */

import { expect, test, type Route } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi, type MockMap } from "./utils/api-mock";
import { commonMocks } from "./utils/common-mocks";

interface OrderFixture {
  id: number;
  company_id: number;
  contact_id: number;
  deal_id: number | null;
  order_number: string;
  total_amount: number | null;
  status: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
  company_name: string | null;
  contact_display_name: string | null;
}

interface ShippingFixture {
  id: number;
  order_id: number;
  tenant_id: number;
  recipient_name: string | null;
  phone: string | null;
  email: string | null;
  tax_number: string | null;
  address1: string | null;
  address2: string | null;
  address3: string | null;
  city: string | null;
  state_code: string | null;
  zip_code: string | null;
  country_code: string | null;
  length_cm: number | null;
  width_cm: number | null;
  height_cm: number | null;
  weight_kg: number | null;
  volume_g: number | null;
  box_count: number | null;
  packing_memo: string | null;
  packing_type: string | null;
  inspection_status: string | null;
  item_description: string | null;
  item_price_usd: number | null;
  exchange_rate: number | null;
  hs_code: string | null;
  tax_id: string | null;
  fedex_id: string | null;
  carrier: string | null;
  ship_method: string | null;
  ship_date: string | null;
  tracking_number: string | null;
  est_shipping_fee: number | null;
  label_issued_at: string | null;
  pickup_requested_at: string | null;
  shipped_at: string | null;
  notified_at: string | null;
  ship_memo: string | null;
  created_at: string;
  updated_at: string;
}

const baseOrder: OrderFixture = {
  id: 1,
  company_id: 11,
  contact_id: 21,
  deal_id: null,
  order_number: "ORD-SHIP-1",
  total_amount: 100000,
  status: "pending",
  notes: null,
  created_at: "2026-05-01T00:00:00+00:00",
  updated_at: "2026-05-10T00:00:00+00:00",
  company_name: "アルファ商事",
  contact_display_name: "アルファ商事の担当",
};

const groupCountsAll = {
  counts: {
    pending: 1,
    confirmed: 0,
    processing: 0,
    shipped: 0,
    delivered: 0,
    returned: 0,
    cancelled: 0,
  },
  total: 1,
};

const emptyShipping: Partial<ShippingFixture> = {};

function buildShipping(input: Partial<ShippingFixture>): ShippingFixture {
  const defaults: ShippingFixture = {
    id: 1,
    order_id: 1,
    tenant_id: 999,
    recipient_name: null,
    phone: null,
    email: null,
    tax_number: null,
    address1: null,
    address2: null,
    address3: null,
    city: null,
    state_code: null,
    zip_code: null,
    country_code: null,
    length_cm: null,
    width_cm: null,
    height_cm: null,
    weight_kg: null,
    volume_g: null,
    box_count: null,
    packing_memo: null,
    packing_type: null,
    inspection_status: null,
    item_description: null,
    item_price_usd: null,
    exchange_rate: null,
    hs_code: null,
    tax_id: null,
    fedex_id: null,
    carrier: null,
    ship_method: null,
    ship_date: null,
    tracking_number: null,
    est_shipping_fee: null,
    label_issued_at: null,
    pickup_requested_at: null,
    shipped_at: null,
    notified_at: null,
    ship_memo: null,
    created_at: "2026-05-11T00:00:00+00:00",
    updated_at: "2026-05-11T00:00:00+00:00",
  };
  return { ...defaults, ...input };
}

/**
 * /orders + /orders/group-counts + /orders/1/financial (404) +
 * /orders/1/shipping (mutable) + CSV download を mock するヘルパー。
 */
function ordersWithShippingMocks(initial: ShippingFixture | null): {
  mocks: MockMap;
  state: { current: ShippingFixture | null; csvCalls: number };
} {
  const state = { current: initial, csvCalls: 0 };
  const mocks: MockMap = {
    ...commonMocks(),
    "GET /companies": [],
    "GET /orders": [baseOrder],
    "GET /orders/group-counts": groupCountsAll,
    // Sprint 2 の財務情報は本テストでは未登録 (404) で問題ない
    "GET /orders/1/financial": async (route: Route) => {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "売上情報が見つかりません" }),
      });
    },
    "GET /orders/1/shipping": async (route: Route) => {
      if (state.current) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(state.current),
        });
      } else {
        await route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({ detail: "発送情報が見つかりません" }),
        });
      }
    },
    "POST /orders/1/shipping": async (route: Route) => {
      const body = JSON.parse(route.request().postData() ?? "{}");
      const next = buildShipping({ order_id: 1, ...body });
      state.current = next;
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(next),
      });
    },
    "PATCH /orders/1/shipping": async (route: Route) => {
      const body = JSON.parse(route.request().postData() ?? "{}");
      const merged = buildShipping({
        ...(state.current ?? { order_id: 1 }),
        ...body,
      });
      state.current = merged;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(merged),
      });
    },
    "GET /orders/1/shipping/elogi-csv": async (route: Route) => {
      state.csvCalls += 1;
      const csv =
        "TIMESTAMP,SHIP_STAFF2,ORDER_TYPE,ORDER_NO,ORDER_DATE,SKU2,IMAGE_URL,PRODUCT_TITLE,QTY2,USD_PRICE,BUYER_ID,RECIPIENT2,PHONE2,EMAIL2,COUNTRY2,STATE_CODE,CITY2,ZIP2,ADDRESS2_1\r\n" +
        "2026-05-11T00:00:00Z,,,ORD-SHIP-1,2026-05-01,,,,,,,Recipient,,,JP,,,,1-1\r\n";
      await route.fulfill({
        status: 200,
        contentType: "text/csv; charset=utf-8",
        headers: {
          "content-disposition": 'attachment; filename="elogi-ORD-SHIP-1.csv"',
        },
        body: csv,
      });
    },
  };
  return { mocks, state };
}

test.describe("ADR-021 Sprint 3: 発送情報 MVP", () => {
  test("受注一覧に追跡番号列と発送編集ボタンが描画される", async ({ page }) => {
    await installAuthBypass(page);
    const { mocks } = ordersWithShippingMocks(null);
    await mockApi(page, mocks);

    await page.goto("/orders");
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });

    // 列ヘッダ「追跡番号」が存在
    await expect(
      page.getByRole("columnheader", { name: "追跡番号" }),
    ).toBeVisible();
    // 発送情報未登録なのでセルはハイフン
    await expect(page.getByTestId("ship-cell-tracking-1")).toHaveText("-");
    // 発送編集ボタンが存在
    await expect(page.getByTestId("open-shipping-1")).toBeVisible();
  });

  test("発送編集を開いて新規登録 → 一覧の追跡番号が更新される", async ({
    page,
  }) => {
    await installAuthBypass(page);
    const { mocks, state } = ordersWithShippingMocks(null);
    await mockApi(page, mocks);

    await page.goto("/orders");
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });

    await page.getByTestId("open-shipping-1").click();
    await expect(page.getByRole("dialog", { name: /配送/ })).toBeVisible();

    await page.getByTestId("ship-input-recipient_name").fill("John Smith");
    await page.getByTestId("ship-input-address1").fill("1 Main St");
    await page.getByTestId("ship-input-country_code").fill("US");
    await page.getByTestId("ship-input-tracking_number").fill("EL12345JP");
    await page.getByTestId("ship-input-carrier").selectOption("elogi");

    await page.getByTestId("ship-save").click();

    await expect(page.getByRole("dialog", { name: /配送/ })).toHaveCount(0);
    await expect(page.getByTestId("ship-cell-tracking-1")).toContainText(
      "EL12345JP",
    );
    expect(state.current?.recipient_name).toBe("John Smith");
    expect(state.current?.carrier).toBe("elogi");
  });

  test("既存発送情報を開くと PATCH で追跡番号を更新できる", async ({ page }) => {
    await installAuthBypass(page);
    const initial = buildShipping({
      recipient_name: "Old",
      tracking_number: "EL000",
      carrier: "elogi",
    });
    const { mocks, state } = ordersWithShippingMocks(initial);
    await mockApi(page, mocks);

    await page.goto("/orders");
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });

    // 初期表示で追跡番号が一覧に出ている
    await expect(page.getByTestId("ship-cell-tracking-1")).toContainText("EL000");

    await page.getByTestId("open-shipping-1").click();
    const tn = page.getByTestId("ship-input-tracking_number");
    await tn.fill("");
    await tn.fill("EL999XYZ");
    await page.getByTestId("ship-save").click();

    await expect(page.getByTestId("ship-cell-tracking-1")).toContainText(
      "EL999XYZ",
    );
    expect(state.current?.tracking_number).toBe("EL999XYZ");
  });

  test("eLogi CSV ダウンロードボタン押下で CSV API が呼ばれる", async ({
    page,
  }) => {
    await installAuthBypass(page);
    const initial = buildShipping({
      recipient_name: "Recipient",
      tracking_number: "EL777",
      carrier: "elogi",
    });
    const { mocks, state } = ordersWithShippingMocks(initial);
    await mockApi(page, mocks);

    await page.goto("/orders");
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });

    await page.getByTestId("open-shipping-1").click();
    await expect(page.getByRole("dialog", { name: /配送/ })).toBeVisible();

    // ダウンロードボタンは「既存発送情報あり」で活性化される
    const dl = page.getByTestId("ship-download-csv");
    await expect(dl).toBeEnabled();

    // download イベントを待ち受けてからクリック
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      dl.click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/^elogi-/);
    expect(state.csvCalls).toBeGreaterThanOrEqual(1);
  });

  test("既存 Sprint 1/2 の UI が引き続き動作する（回帰）", async ({ page }) => {
    await installAuthBypass(page);
    const { mocks } = ordersWithShippingMocks(null);
    await mockApi(page, mocks);

    await page.goto("/orders");
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });

    // Sprint 1 検索 / ソート / 件数バッジ
    await expect(page.getByTestId("orders-search-input")).toBeVisible();
    await expect(page.getByTestId("orders-sort-by")).toBeVisible();
    await expect(page.getByTestId("orders-sort-order")).toBeVisible();
    await expect(page.getByTestId("group-count-all")).toBeVisible();
    // Sprint 2 売上編集ボタン
    await expect(page.getByTestId("open-financial-1")).toBeVisible();
  });
});
