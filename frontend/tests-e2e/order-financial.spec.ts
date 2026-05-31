/**
 * ADR-021 Phase 2 / Sprint 2 — 売上計算 MVP の E2E テスト。
 *
 * 検証範囲（spec.md AC-2.7）:
 *   - 受注一覧から「売上編集」を開いて売上情報フォームが表示される
 *   - 売上高・仕入原価・PayPal手数料 を入力 → 保存 → 一覧の売上 / 粗利 / 粗利率 列が更新
 *   - 既存売上情報は PATCH、未登録は POST に振り分けられる（404 → 新規）
 *   - 既存 Sprint 1 の検索・ソート・件数バッジ E2E が壊れない（同じ data-testid を維持）
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

interface FinancialFixture {
  id: number;
  order_id: number;
  tenant_id: number;
  revenue_amount: number;
  purchase_cost: number;
  purchase_shipping: number;
  paypal_fee: number;
  wise_fee: number;
  exchange_fee: number;
  outsource_fee: number;
  packing_fee: number;
  ad_cost: number;
  return_fee: number;
  refund_amount: number;
  commission_base_amount: number;
  tax_refund: number;
  notes: string | null;
  cost_total: number;
  gross_profit: number;
  gross_profit_rate: number | null;
  operating_profit_with_tax_refund: number;
  created_at: string;
  updated_at: string;
}

const baseOrder: OrderFixture = {
  id: 1,
  company_id: 11,
  contact_id: 21,
  deal_id: null,
  order_number: "ORD-FIN-1",
  total_amount: 100000,
  status: "awaiting_payment",
  notes: null,
  created_at: "2026-05-01T00:00:00+00:00",
  updated_at: "2026-05-10T00:00:00+00:00",
  company_name: "アルファ商事",
  contact_display_name: "アルファ商事の担当",
};

const groupCountsAll = {
    counts: {
    awaiting_payment: 0,
    sourcing: 0,
    awaiting_shipping: 0,
    completed: 1,
    trouble: 0,
    cancelled: 0,
  },
  total: 1,
};

function buildFinancial(input: Partial<FinancialFixture>): FinancialFixture {
  const defaults: FinancialFixture = {
    id: 1,
    order_id: 1,
    tenant_id: 999,
    revenue_amount: 0,
    purchase_cost: 0,
    purchase_shipping: 0,
    paypal_fee: 0,
    wise_fee: 0,
    exchange_fee: 0,
    outsource_fee: 0,
    packing_fee: 0,
    ad_cost: 0,
    return_fee: 0,
    refund_amount: 0,
    commission_base_amount: 0,
    tax_refund: 0,
    notes: null,
    cost_total: 0,
    gross_profit: 0,
    gross_profit_rate: null,
    operating_profit_with_tax_refund: 0,
    created_at: "2026-05-11T00:00:00+00:00",
    updated_at: "2026-05-11T00:00:00+00:00",
  };
  const merged = { ...defaults, ...input };
  // 導出列を再計算（テストで指定漏れがあっても整合させる）
  const cost =
    merged.purchase_cost +
    merged.purchase_shipping +
    merged.paypal_fee +
    merged.wise_fee +
    merged.exchange_fee +
    merged.outsource_fee +
    merged.packing_fee +
    merged.ad_cost +
    merged.return_fee +
    merged.refund_amount;
  merged.cost_total = cost;
  merged.gross_profit = merged.revenue_amount - cost;
  merged.gross_profit_rate =
    merged.revenue_amount === 0 ? null : merged.gross_profit / merged.revenue_amount;
  merged.operating_profit_with_tax_refund = merged.gross_profit + merged.tax_refund;
  return merged;
}

/**
 * /orders + /orders/group-counts + /orders/1/financial を mock するヘルパー。
 * パネル保存（POST/PATCH）を捕捉できるよう mutable な financial state を持つ。
 */
function ordersWithFinancialMocks(initial: FinancialFixture | null): {
  mocks: MockMap;
  state: { current: FinancialFixture | null };
} {
  const state = { current: initial };
  const mocks: MockMap = {
    ...commonMocks(),
    "GET /companies": [],
    "GET /orders": [baseOrder],
    "GET /orders/group-counts": groupCountsAll,
    "GET /orders/1/financial": async (route: Route) => {
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
          body: JSON.stringify({ detail: "売上情報が見つかりません" }),
        });
      }
    },
    "POST /orders/1/financial": async (route: Route) => {
      const body = JSON.parse(route.request().postData() ?? "{}");
      const next = buildFinancial({ order_id: 1, ...body });
      state.current = next;
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(next),
      });
    },
    "PATCH /orders/1/financial": async (route: Route) => {
      const body = JSON.parse(route.request().postData() ?? "{}");
      const merged: FinancialFixture = buildFinancial({
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
  };
  return { mocks, state };
}

test.describe("ADR-021 Sprint 2: 売上計算 MVP", () => {
  test("受注一覧に売上 / 粗利 / 粗利率 列が描画される（売上情報未登録ならハイフン）", async ({
    page,
  }) => {
    await installAuthBypass(page);
    const { mocks } = ordersWithFinancialMocks(null);
    await mockApi(page, mocks);

    await page.goto("/orders");
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });

    // 列ヘッダ。「粗利」と「粗利率」が部分一致で衝突するので exact:true で限定
    await expect(page.getByRole("columnheader", { name: "売上", exact: true })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "粗利", exact: true })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "粗利率" })).toBeVisible();

    // 売上情報未登録なので - が並ぶ
    await expect(page.getByTestId("fin-cell-revenue-1")).toHaveText("-");
    await expect(page.getByTestId("fin-cell-gross-1")).toHaveText("-");
    await expect(page.getByTestId("fin-cell-rate-1")).toHaveText("-");

    // 「売上編集」ボタンが描画される
    await expect(page.getByTestId("open-financial-1")).toBeVisible();
  });

  test("売上編集を開いて新規登録 → 一覧の粗利 / 粗利率が更新される", async ({
    page,
  }) => {
    await installAuthBypass(page);
    const { mocks } = ordersWithFinancialMocks(null);
    await mockApi(page, mocks);

    await page.goto("/orders");
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });

    // 売上編集ボタン押下 → モーダル表示
    await page.getByTestId("open-financial-1").click();
    await expect(page.getByRole("dialog", { name: /売上高/ })).toBeVisible();

    // 入力: revenue=100000, purchase_cost=60000, paypal_fee=3000
    await page.getByTestId("fin-input-revenue_amount").fill("100000");
    await page.getByTestId("fin-input-purchase_cost").fill("60000");
    await page.getByTestId("fin-input-paypal_fee").fill("3000");

    // プレビュー: 粗利 = 100000 - 63000 = 37000, 粗利率 = 37.0%
    await expect(page.getByTestId("fin-cost-total")).toContainText(/63,000/);
    await expect(page.getByTestId("fin-gross-profit")).toContainText(/37,000/);
    await expect(page.getByTestId("fin-gross-profit-rate")).toContainText(/37\.0%/);

    // 保存
    await page.getByTestId("fin-save").click();

    // モーダルが閉じ、一覧の売上 / 粗利 / 粗利率が更新される
    await expect(page.getByRole("dialog", { name: /売上高/ })).toHaveCount(0);
    await expect(page.getByTestId("fin-cell-revenue-1")).toContainText(/100,000/);
    await expect(page.getByTestId("fin-cell-gross-1")).toContainText(/37,000/);
    await expect(page.getByTestId("fin-cell-rate-1")).toContainText(/37\.0%/);
  });

  test("既存売上情報を開くと PATCH でフィールド更新できる", async ({ page }) => {
    await installAuthBypass(page);
    const initial = buildFinancial({
      revenue_amount: 50000,
      purchase_cost: 20000,
    });
    const { mocks, state } = ordersWithFinancialMocks(initial);
    await mockApi(page, mocks);

    await page.goto("/orders");
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });

    // 初期表示: 売上 50,000 / 粗利 30,000 / 粗利率 60.0%
    await expect(page.getByTestId("fin-cell-revenue-1")).toContainText(/50,000/);
    await expect(page.getByTestId("fin-cell-gross-1")).toContainText(/30,000/);
    await expect(page.getByTestId("fin-cell-rate-1")).toContainText(/60\.0%/);

    // パネル開いて purchase_cost を 30000 に上書き → 粗利 20000 / 粗利率 40%
    await page.getByTestId("open-financial-1").click();
    const cost = page.getByTestId("fin-input-purchase_cost");
    await cost.fill("");
    await cost.fill("30000");
    await page.getByTestId("fin-save").click();

    await expect(page.getByTestId("fin-cell-gross-1")).toContainText(/20,000/);
    await expect(page.getByTestId("fin-cell-rate-1")).toContainText(/40\.0%/);
    // PATCH 後の state は purchase_cost=30000 になっている
    expect(state.current?.purchase_cost).toBe(30000);
  });

  test("既存 Sprint 1 の検索 / ソート UI が引き続き動作する（回帰）", async ({
    page,
  }) => {
    await installAuthBypass(page);
    const { mocks } = ordersWithFinancialMocks(null);
    await mockApi(page, mocks);

    await page.goto("/orders");
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });

    // Sprint 1 で追加された data-testid が引き続き存在する
    await expect(page.getByTestId("orders-search-input")).toBeVisible();
    await expect(page.getByTestId("orders-sort-by")).toBeVisible();
    await expect(page.getByTestId("orders-sort-order")).toBeVisible();
    await expect(page.getByTestId("subnav-all")).toBeVisible();
    await expect(page.getByTestId("subnav-awaiting_payment")).toBeVisible();
  });
});
