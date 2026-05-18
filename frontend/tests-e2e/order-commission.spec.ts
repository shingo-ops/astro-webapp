/**
 * ADR-021 Phase 5 / Sprint 5 — 担当者報酬計算 MVP の E2E テスト。
 *
 * 検証範囲（spec.md AC-5.9 / AC-5.10）:
 *   - 受注一覧から「報酬編集」を開いて 5 ロール × 担当者 select が表示される
 *   - 担当者を assign すると POST /orders/{id}/commissions/assign が呼ばれる
 *   - 「再計算」ボタンが POST /orders/{id}/commissions/recalc を呼び、
 *     一覧の「報酬合計」セルに金額が反映される
 *   - CommissionSettingsPage で rate を変更 → 保存で
 *     PATCH /tenant-commission-settings が呼ばれる
 *
 * Backend は API mock 経由で固定（実際の計算ロジックは backend pytest 側で検証済）。
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

interface CommissionRow {
  id: number;
  order_id: number;
  tenant_id: number;
  role: string;
  staff_id: number | null;
  staff_name: string | null;
  calculated_amount: number;
  calculated_at: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

const baseOrder: OrderFixture = {
  id: 1,
  company_id: 11,
  contact_id: 21,
  deal_id: null,
  order_number: "ORD-COM-1",
  total_amount: 100000,
  status: "confirmed",
  notes: null,
  created_at: "2026-05-01T00:00:00+00:00",
  updated_at: "2026-05-10T00:00:00+00:00",
  company_name: "アルファ商事",
  contact_display_name: "アルファ商事の担当",
};

const groupCountsAll = {
  counts: {
    pending: 0,
    confirmed: 1,
    processing: 0,
    shipped: 0,
    delivered: 0,
    returned: 0,
    cancelled: 0,
  },
  total: 1,
};

const staffList = [
  {
    id: 100,
    surname_jp: "山田",
    given_name_jp: "太郎",
    primary_email: "yamada@example.com",
    is_employee: false,
  },
  {
    id: 200,
    surname_jp: "佐藤",
    given_name_jp: "花子",
    primary_email: "sato@example.com",
    is_employee: false,
  },
];

function emptyCommissions(): Record<string, CommissionRow | null> {
  return {
    sales: null,
    order: null,
    ship: null,
    purchase: null,
    trouble: null,
  };
}

function buildCommissionRow(role: string, staff_id: number | null): CommissionRow {
  const staff = staffList.find((s) => s.id === staff_id) ?? null;
  return {
    id: 10000 + Math.floor(Math.random() * 1000),
    order_id: 1,
    tenant_id: 999,
    role,
    staff_id: staff_id,
    staff_name: staff ? `${staff.surname_jp} ${staff.given_name_jp}` : null,
    calculated_amount: 0,
    calculated_at: null,
    notes: null,
    created_at: "2026-05-11T00:00:00+00:00",
    updated_at: "2026-05-11T00:00:00+00:00",
  };
}

interface MockState {
  commissions: Record<string, CommissionRow | null>;
  recalcCalls: number;
  patchSettingsCalls: number;
  lastPatchedRates: unknown;
}

function ordersWithCommissionMocks(initial?: Record<string, CommissionRow | null>): {
  mocks: MockMap;
  state: MockState;
} {
  const state: MockState = {
    commissions: initial ?? emptyCommissions(),
    recalcCalls: 0,
    patchSettingsCalls: 0,
    lastPatchedRates: null,
  };

  const mocks: MockMap = {
    ...commonMocks(),
    "GET /companies": [],
    "GET /orders": [baseOrder],
    "GET /orders/group-counts": groupCountsAll,
    "GET /staff": staffList,
    // 既存 Sprint 2/3/4 は本テスト未登録 (404)
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
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "仕入情報が見つかりません" }),
      });
    },
    "GET /orders/1/commissions": async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          order_id: 1,
          commissions: state.commissions,
        }),
      });
    },
    "POST /orders/1/commissions/assign": async (route: Route) => {
      const body = JSON.parse(route.request().postData() ?? "{}");
      const role = body.role as string;
      const sid = body.staff_id as number | null;
      const row = buildCommissionRow(role, sid);
      state.commissions[role] = row;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(row),
      });
    },
    "POST /orders/1/commissions/recalc": async (route: Route) => {
      state.recalcCalls += 1;
      // 簡易計算: 営業/受注=staff 割当時 1000, 発送=200, 仕入=100, トラブル=500
      const amounts: Record<string, number> = {
        sales: 1000,
        order: 1000,
        ship: 200,
        purchase: 100,
        trouble: 500,
      };
      const updated: Record<string, CommissionRow | null> = {};
      for (const role of ["sales", "order", "ship", "purchase", "trouble"]) {
        const cur = state.commissions[role];
        if (cur && cur.staff_id !== null) {
          updated[role] = {
            ...cur,
            calculated_amount: amounts[role],
            calculated_at: "2026-05-11T00:00:00+00:00",
          };
        } else {
          updated[role] = cur;
        }
      }
      state.commissions = updated;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          order_id: 1,
          commissions: state.commissions,
        }),
      });
    },
    // CommissionSettingsPage 用
    "GET /tenant-commission-settings": async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: 1,
          tenant_id: 999,
          commission_rates: {
            sales: { type: "rate", value: 0.1 },
            order: { type: "rate", value: 0.1 },
            ship: { type: "fixed", value: 200 },
            purchase: { type: "fixed", value: 100 },
            trouble: { type: "fixed", value: 500 },
          },
          created_at: "2026-05-11T00:00:00+00:00",
          updated_at: "2026-05-11T00:00:00+00:00",
        }),
      });
    },
    "PATCH /tenant-commission-settings": async (route: Route) => {
      state.patchSettingsCalls += 1;
      const body = JSON.parse(route.request().postData() ?? "{}");
      state.lastPatchedRates = body.commission_rates;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: 1,
          tenant_id: 999,
          commission_rates: body.commission_rates,
          created_at: "2026-05-11T00:00:00+00:00",
          updated_at: "2026-05-11T00:00:01+00:00",
        }),
      });
    },
    "GET /commissions/monthly": async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          year: 2026,
          month: 5,
          by_staff: [],
          by_role: [],
          total: 0,
        }),
      });
    },
  };
  return { mocks, state };
}

test.describe("ADR-021 Sprint 5: 担当者報酬計算 MVP — 一覧 + パネル", () => {
  test("受注一覧に「報酬合計」列と「報酬編集」ボタンが描画される", async ({
    page,
  }) => {
    await installAuthBypass(page);
    const { mocks } = ordersWithCommissionMocks();
    await mockApi(page, mocks);

    await page.goto("/orders");
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });

    // ADR-044: i18n 化により列ヘッダは t("orders.commission") = "報酬"
    await expect(
      page.getByRole("columnheader", { name: "報酬", exact: true }),
    ).toBeVisible();
    // 未登録なので "-"
    await expect(page.getByTestId("com-cell-total-1")).toContainText("-");
    await expect(page.getByTestId("open-commission-1")).toBeVisible();
  });

  test("「報酬編集」を開いて 5 ロールの担当者 select が表示される", async ({
    page,
  }) => {
    await installAuthBypass(page);
    const { mocks } = ordersWithCommissionMocks();
    await mockApi(page, mocks);

    await page.goto("/orders");
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });

    await page.getByTestId("open-commission-1").click();
    await expect(page.getByRole("dialog", { name: /担当者/ })).toBeVisible();

    // 5 ロール分の select
    for (const role of ["sales", "order", "ship", "purchase", "trouble"]) {
      await expect(page.getByTestId(`commission-staff-${role}`)).toBeVisible();
    }
  });

  test("担当者 assign → 再計算で「報酬合計」セルが更新される", async ({
    page,
  }) => {
    await installAuthBypass(page);
    const { mocks, state } = ordersWithCommissionMocks();
    await mockApi(page, mocks);

    await page.goto("/orders");
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });

    await page.getByTestId("open-commission-1").click();
    await expect(page.getByRole("dialog", { name: /担当者/ })).toBeVisible();

    // 営業 = 山田、発送 = 佐藤
    await page
      .getByTestId("commission-staff-sales")
      .selectOption(String(staffList[0].id));
    await page
      .getByTestId("commission-staff-ship")
      .selectOption(String(staffList[1].id));

    // 再計算
    await page.getByTestId("commission-recalc").click();
    expect(state.recalcCalls).toBeGreaterThanOrEqual(1);

    // パネル内に金額が反映される
    await expect(page.getByTestId("commission-amount-sales")).toContainText(
      "1,000",
    );
    await expect(page.getByTestId("commission-amount-ship")).toContainText("200");

    // モーダルを閉じて一覧の合計セルを確認
    await page
      .getByRole("dialog", { name: /担当者/ })
      .getByRole("button", { name: "閉じる" })
      .click();
    await expect(page.getByRole("dialog", { name: /担当者/ })).toHaveCount(0);

    // 営業 1000 + 発送 200 = 1200
    await expect(page.getByTestId("com-cell-total-1")).toContainText("1,200");
  });

  test("既存 Sprint 1/2/3/4 の UI が引き続き動作する（回帰）", async ({
    page,
  }) => {
    await installAuthBypass(page);
    const { mocks } = ordersWithCommissionMocks();
    await mockApi(page, mocks);

    await page.goto("/orders");
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });

    // Sprint 1 検索 / ソート / 件数バッジ
    await expect(page.getByTestId("orders-search-input")).toBeVisible();
    await expect(page.getByTestId("orders-sort-by")).toBeVisible();
    await expect(page.getByTestId("group-count-all")).toBeVisible();
    // Sprint 2 売上編集 / Sprint 3 発送編集 / Sprint 4 仕入編集
    await expect(page.getByTestId("open-financial-1")).toBeVisible();
    await expect(page.getByTestId("open-shipping-1")).toBeVisible();
    await expect(page.getByTestId("open-purchase-1")).toBeVisible();
  });
});

test.describe("ADR-021 Sprint 5: 報酬設定ページ", () => {
  test("rate を変更 → 保存で PATCH が呼ばれる", async ({ page }) => {
    await installAuthBypass(page);
    const { mocks, state } = ordersWithCommissionMocks();
    await mockApi(page, mocks);

    await page.goto("/commission-settings");
    await expect(page.getByRole("heading", { name: /報酬設定/ })).toBeVisible({
      timeout: 20_000,
    });

    // 初期値が描画される
    const salesValue = page.getByTestId("settings-value-sales");
    await expect(salesValue).toHaveValue("0.1");

    // 営業 rate を 20% に変更
    await salesValue.fill("0.2");
    // 発送 fixed を 300 円に変更
    await page.getByTestId("settings-value-ship").fill("300");

    await page.getByTestId("settings-save").click();

    // 保存メッセージが表示される
    // ADR-044: i18n 化により info メッセージは t("common.saving") = "保存中..." を表示
    await expect(page.getByText("保存中...")).toBeVisible({ timeout: 5_000 });
    expect(state.patchSettingsCalls).toBeGreaterThanOrEqual(1);

    // 送信された rates を検証
    const last = state.lastPatchedRates as Record<string, { type: string; value: number }>;
    expect(last.sales.value).toBeCloseTo(0.2);
    expect(last.ship.value).toBe(300);
  });

  test("月次集計が描画される", async ({ page }) => {
    await installAuthBypass(page);
    const { mocks } = ordersWithCommissionMocks();
    await mockApi(page, mocks);

    await page.goto("/commission-settings");
    await expect(page.getByRole("heading", { name: /報酬設定/ })).toBeVisible({
      timeout: 20_000,
    });

    await expect(page.getByTestId("monthly-total")).toBeVisible();
    await expect(page.getByTestId("monthly-total")).toContainText("0");
  });
});
