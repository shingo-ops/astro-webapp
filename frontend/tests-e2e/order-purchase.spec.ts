/**
 * ADR-021 Phase 4 / Sprint 4 — 仕入情報 MVP の E2E テスト。
 *
 * 検証範囲（spec.md AC-4.6）:
 *   - 受注一覧から「仕入編集」を開いて仕入情報フォームが表示される
 *   - 仕入元 / 取引番号 / 金額・数量 を入力 → 保存 → 一覧の仕入状況バッジが更新
 *   - 既存仕入情報は PATCH、未登録は POST に振り分けられる（404 → 新規）
 *   - パネル内の「確定」ボタンが PATCH /orders/{id}/purchase/status を呼び出す
 *   - 既存 Sprint 1 / 2 / 3 の検索 / ソート / 売上編集 / 発送編集が壊れない
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

interface PurchaseFixture {
  id: number;
  order_id: number;
  tenant_id: number;
  purchase_staff: string | null;
  purchase_date: string | null;
  transaction_no: string | null;
  supplier_name: string | null;
  supplier_url: string | null;
  purchase_amount: number | null;
  purchase_quantity: number | null;
  purchase_total: number | null;
  purchase_shipping: number | null;
  carrier_name: string | null;
  waybill_no: string | null;
  purchase_note: string | null;
  purchase_status: string | null;
  total_with_shipping: number | null;
  created_at: string;
  updated_at: string;
}

const baseOrder: OrderFixture = {
  id: 1,
  company_id: 11,
  contact_id: 21,
  deal_id: null,
  order_number: "ORD-PUR-1",
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

function buildPurchase(input: Partial<PurchaseFixture>): PurchaseFixture {
  const total = input.purchase_total ?? 0;
  const shipping = input.purchase_shipping ?? 0;
  const defaults: PurchaseFixture = {
    id: 1,
    order_id: 1,
    tenant_id: 999,
    purchase_staff: null,
    purchase_date: null,
    transaction_no: null,
    supplier_name: null,
    supplier_url: null,
    purchase_amount: null,
    purchase_quantity: null,
    purchase_total: null,
    purchase_shipping: null,
    carrier_name: null,
    waybill_no: null,
    purchase_note: null,
    purchase_status: "",
    total_with_shipping: Number(total) + Number(shipping),
    created_at: "2026-05-11T00:00:00+00:00",
    updated_at: "2026-05-11T00:00:00+00:00",
  };
  return { ...defaults, ...input };
}

/**
 * /orders + /orders/group-counts + /orders/1/financial (404) +
 * /orders/1/shipping (404) + /orders/1/purchase (mutable) を mock するヘルパー。
 */
function ordersWithPurchaseMocks(initial: PurchaseFixture | null): {
  mocks: MockMap;
  state: { current: PurchaseFixture | null; statusCalls: number };
} {
  const state = { current: initial, statusCalls: 0 };
  const mocks: MockMap = {
    ...commonMocks(),
    "GET /companies": [],
    "GET /orders": [baseOrder],
    "GET /orders/group-counts": groupCountsAll,
    // Sprint 2 売上情報・Sprint 3 発送情報は本テスト未登録 (404)
    "GET /orders/1/financial": async (route: Route) => {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "売上情報が見つかりません" }),
      });
    },
    "GET /orders/1/shipping": async (route: Route) => {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "発送情報が見つかりません" }),
      });
    },
    "GET /orders/1/purchase": async (route: Route) => {
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
          body: JSON.stringify({ detail: "仕入情報が見つかりません" }),
        });
      }
    },
    "POST /orders/1/purchase": async (route: Route) => {
      const body = JSON.parse(route.request().postData() ?? "{}");
      const next = buildPurchase({ order_id: 1, ...body });
      state.current = next;
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(next),
      });
    },
    "PATCH /orders/1/purchase": async (route: Route) => {
      const body = JSON.parse(route.request().postData() ?? "{}");
      const merged = buildPurchase({
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
    "PATCH /orders/1/purchase/status": async (route: Route) => {
      state.statusCalls += 1;
      const body = JSON.parse(route.request().postData() ?? "{}");
      const next = buildPurchase({
        ...(state.current ?? { order_id: 1 }),
        purchase_status: body.status ?? "confirmed",
      });
      state.current = next;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(next),
      });
    },
  };
  return { mocks, state };
}

test.describe("ADR-021 Sprint 4: 仕入情報 MVP", () => {
  test("受注一覧に仕入状況列と仕入編集ボタンが描画される", async ({ page }) => {
    await installAuthBypass(page);
    const { mocks } = ordersWithPurchaseMocks(null);
    await mockApi(page, mocks);

    await page.goto("/orders");
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });

    // ADR-044: i18n 化により列ヘッダは t("orders.purchase") = "仕入"
    await expect(
      page.getByRole("columnheader", { name: "仕入", exact: true }),
    ).toBeVisible();
    // 仕入情報未登録なのでセルは t("common.notSet") = "未設定"
    await expect(page.getByTestId("pur-cell-status-1")).toContainText("未設定");
    // 仕入編集ボタンが存在
    await expect(page.getByTestId("open-purchase-1")).toBeVisible();
  });

  test("仕入編集を開いて新規登録 → 一覧の仕入状況が確認中に更新される", async ({
    page,
  }) => {
    await installAuthBypass(page);
    const { mocks, state } = ordersWithPurchaseMocks(null);
    await mockApi(page, mocks);

    await page.goto("/orders");
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });

    await page.getByTestId("open-purchase-1").click();
    await expect(page.getByRole("dialog", { name: /仕入情報/ })).toBeVisible();

    await page.getByTestId("pur-input-purchase_staff").fill("山田 太郎");
    await page.getByTestId("pur-input-supplier_name").fill("アルファ仕入元");
    await page.getByTestId("pur-input-transaction_no").fill("TX-001");
    await page.getByTestId("pur-input-purchase_total").fill("15000");
    await page.getByTestId("pur-input-purchase_shipping").fill("2000");

    await page.getByTestId("pur-save").click();

    await expect(page.getByRole("dialog", { name: /仕入情報/ })).toHaveCount(0);
    await expect(page.getByTestId("pur-cell-status-1")).toContainText("確認中");
    expect(state.current?.supplier_name).toBe("アルファ仕入元");
    expect(state.current?.transaction_no).toBe("TX-001");
    expect(Number(state.current?.purchase_total)).toBe(15000);
  });

  test("既存仕入情報を開くと PATCH で内容を更新できる", async ({ page }) => {
    await installAuthBypass(page);
    const initial = buildPurchase({
      supplier_name: "Old Supplier",
      transaction_no: "TX-OLD",
      purchase_total: 1000,
      purchase_status: "",
    });
    const { mocks, state } = ordersWithPurchaseMocks(initial);
    await mockApi(page, mocks);

    await page.goto("/orders");
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });

    // 初期表示で「確認中」
    await expect(page.getByTestId("pur-cell-status-1")).toContainText("確認中");

    await page.getByTestId("open-purchase-1").click();
    const tx = page.getByTestId("pur-input-transaction_no");
    await tx.fill("");
    await tx.fill("TX-NEW");
    await page.getByTestId("pur-save").click();

    await expect(page.getByRole("dialog", { name: /仕入情報/ })).toHaveCount(0);
    expect(state.current?.transaction_no).toBe("TX-NEW");
  });

  test("「確定」ボタン押下で status API が呼ばれて確定済みバッジに切り替わる", async ({
    page,
  }) => {
    await installAuthBypass(page);
    const initial = buildPurchase({
      supplier_name: "Confirmer",
      purchase_total: 5000,
      purchase_status: "",
    });
    const { mocks, state } = ordersWithPurchaseMocks(initial);
    await mockApi(page, mocks);

    await page.goto("/orders");
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });

    await page.getByTestId("open-purchase-1").click();
    await expect(page.getByRole("dialog", { name: /仕入情報/ })).toBeVisible();

    // 確定ボタンは「既存仕入情報あり」で活性化される
    const confirm = page.getByTestId("pur-confirm");
    await expect(confirm).toBeEnabled();
    await confirm.click();

    // モーダルは閉じない（「確定」だけ反映）。閉じてから一覧側を確認する。
    // 状態が反映されるまでの非同期は Playwright が auto-wait する。
    await page
      .getByRole("dialog", { name: /仕入情報/ })
      .getByRole("button", { name: "キャンセル" })
      .click();
    await expect(page.getByRole("dialog", { name: /仕入情報/ })).toHaveCount(0);

    await expect(page.getByTestId("pur-cell-status-1")).toContainText(
      "確定済み",
    );
    expect(state.statusCalls).toBeGreaterThanOrEqual(1);
    expect(state.current?.purchase_status).toBe("confirmed");
  });

  test("既存 Sprint 1/2/3 の UI が引き続き動作する（回帰）", async ({ page }) => {
    await installAuthBypass(page);
    const { mocks } = ordersWithPurchaseMocks(null);
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
    // Sprint 2 売上編集ボタン / Sprint 3 発送編集ボタン
    await expect(page.getByTestId("open-financial-1")).toBeVisible();
    await expect(page.getByTestId("open-shipping-1")).toBeVisible();
  });
});
