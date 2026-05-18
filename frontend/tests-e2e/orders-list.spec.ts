/**
 * ADR-021 Phase 1 / Sprint 1 — 受注一覧 MVP の E2E テスト。
 *
 * 検証範囲（spec.md AC-1.5 / AC-1.6 / AC-1.7 / AC-1.9）:
 *   - 検索ボックスとソート UI が描画される
 *   - 検索キーワード入力で API 呼び出しに `search=` が含まれる
 *   - ソート切替で API の `sort_by` / `sort_order` が変わる
 *   - グループ件数バッジが描画され、検索キーワードに連動して再取得される
 *   - ステータス表示ラベルが ADR-021 の 6 値（未処理/仕入中/配送中/完了/トラブル/キャンセル）
 *
 * Backend は ADR-019/020 の英語UI 影響を受けない API mock 経由で固定。
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

const baseOrder: OrderFixture = {
  id: 1,
  company_id: 11,
  contact_id: 21,
  deal_id: null,
  order_number: "ORD-LIST-1",
  total_amount: 50000,
  status: "pending",
  notes: null,
  created_at: "2026-05-01T00:00:00+00:00",
  updated_at: "2026-05-10T00:00:00+00:00",
  company_name: "アルファ商事",
  contact_display_name: "アルファ商事の担当",
};

const otherOrder: OrderFixture = {
  ...baseOrder,
  id: 2,
  order_number: "ORD-LIST-2",
  total_amount: 200000,
  status: "shipped",
  company_id: 12,
  contact_id: 22,
  company_name: "ベータ工業",
  contact_display_name: "ベータ工業の担当",
};

const allOrders = [baseOrder, otherOrder];

const groupCountsAll = {
  counts: {
    pending: 1,
    confirmed: 0,
    processing: 0,
    shipped: 1,
    delivered: 0,
    returned: 0,
    cancelled: 0,
  },
  total: 2,
};

const groupCountsAlpha = {
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

/**
 * /orders と /orders/group-counts を一括 mock するヘルパー。
 * 個別 spec で動的応答を試したい場合は別途 page.route で上書きする。
 */
function ordersMocks(): MockMap {
  return {
    ...commonMocks(),
    "GET /companies": [],
    // /orders / /orders/group-counts は handler ベースで request URL を解析する
    // （path 一致では query string がパースできないため、function entry を渡す）
    "GET /orders": async (route: Route) => {
      const url = new URL(route.request().url());
      const search = url.searchParams.get("search") ?? "";
      let filtered = allOrders;
      if (search) {
        filtered = allOrders.filter(
          (o) =>
            o.order_number.includes(search) ||
            (o.company_name ?? "").includes(search) ||
            (o.contact_display_name ?? "").includes(search),
        );
      }
      const sortBy = url.searchParams.get("sort_by") ?? "updated_at";
      const sortOrder = url.searchParams.get("sort_order") ?? "desc";
      const sorted = [...filtered].sort((a, b) => {
        const av = (a as unknown as Record<string, unknown>)[sortBy];
        const bv = (b as unknown as Record<string, unknown>)[sortBy];
        if (av === bv) return 0;
        const cmp =
          typeof av === "number" && typeof bv === "number"
            ? av - bv
            : String(av).localeCompare(String(bv));
        return sortOrder === "asc" ? cmp : -cmp;
      });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(sorted),
      });
    },
    "GET /orders/group-counts": async (route: Route) => {
      const url = new URL(route.request().url());
      const search = url.searchParams.get("search") ?? "";
      const body = search.includes("アルファ") ? groupCountsAlpha : groupCountsAll;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    },
  };
}

test.describe("ADR-021 Sprint 1: 受注一覧 MVP", () => {
  test("検索ボックス・ソート UI・件数バッジが描画される", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, ordersMocks());

    await page.goto("/orders");

    // ページタイトル
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });

    // 検索ボックス（ADR-044: i18n 化以降 aria-label が t() ベースになったため
    // testid で指定する。placeholder は t("common.search") = "検索"）
    const searchBox = page.getByTestId("orders-search-input");
    await expect(searchBox).toBeVisible();
    await expect(searchBox).toHaveAttribute("placeholder", /検索/);

    // ソート対象 select
    await expect(page.getByTestId("orders-sort-by")).toBeVisible();
    // ソート順切替ボタン
    await expect(page.getByTestId("orders-sort-order")).toBeVisible();

    // グループ件数バッジ（ADR-021 第 1 節の 6 ステータス + 全件、J1 で confirmed 撤去）
    await expect(page.getByTestId("group-count-all")).toBeVisible();
    for (const s of [
      "pending",
      "processing",
      "shipped",
      "delivered",
      "returned",
      "cancelled",
    ]) {
      await expect(page.getByTestId(`group-count-${s}`)).toBeVisible();
    }

    // ADR-021 第 1 節の 6 値ラベル
    await expect(page.getByTestId("group-count-pending")).toContainText(/未処理/);
    await expect(page.getByTestId("group-count-processing")).toContainText(/仕入中/);
    await expect(page.getByTestId("group-count-shipped")).toContainText(/配送中/);
    await expect(page.getByTestId("group-count-delivered")).toContainText(/完了/);
    await expect(page.getByTestId("group-count-returned")).toContainText(/トラブル/);
    await expect(page.getByTestId("group-count-cancelled")).toContainText(/キャンセル/);
  });

  test("初期表示で受注行が表示され、JOIN 列（会社名/担当者名）が出る", async ({
    page,
  }) => {
    await installAuthBypass(page);
    await mockApi(page, ordersMocks());

    await page.goto("/orders");
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });

    // ヘッダ「会社」「名前」列（ADR-044: i18n 化により担当者 → 名前 t("common.name")）
    await expect(page.getByRole("columnheader", { name: "会社" })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "名前" })).toBeVisible();

    // データ行（API mock の company_name / contact_display_name が表示）
    await expect(page.getByRole("cell", { name: "ORD-LIST-1" })).toBeVisible();
    // 部分一致で他レコードと衝突するので exact: true で限定
    await expect(
      page.getByRole("cell", { name: "アルファ商事", exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("cell", { name: "アルファ商事の担当" })).toBeVisible();
  });

  test("検索ボックスで絞り込みすると一覧と件数バッジが連動する", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, ordersMocks());

    await page.goto("/orders");
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });
    // 初期: 2 件表示
    await expect(page.getByRole("cell", { name: "ORD-LIST-1" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "ORD-LIST-2" })).toBeVisible();

    // 検索: 「アルファ」 → ORD-LIST-1 のみ
    const searchBox = page.getByTestId("orders-search-input");
    await searchBox.fill("アルファ");

    // debounce 300ms 後に API が叩かれて reload される
    await expect(page.getByRole("cell", { name: "ORD-LIST-1" })).toBeVisible({
      timeout: 5_000,
    });
    await expect(page.getByRole("cell", { name: "ORD-LIST-2" })).toHaveCount(0);

    // 件数バッジも連動: total が 1 になる（mock の groupCountsAlpha）
    await expect(page.getByTestId("group-count-all")).toContainText(/\(1\)/);
    await expect(page.getByTestId("group-count-pending")).toContainText(/\(1\)/);
    await expect(page.getByTestId("group-count-shipped")).toContainText(/\(0\)/);
  });

  test("ソート切替で API 呼び出しの sort_by / sort_order が変わる", async ({
    page,
  }) => {
    await installAuthBypass(page);

    // ソート関連リクエスト URL を捕捉する。
    // mockApi の /api/v1/.* generic handler を先に登録し、その後で具体的な
    // /orders matcher を上書き登録する（Playwright は後勝ち優先のため）。
    await mockApi(page, {
      ...commonMocks(),
      "GET /companies": [],
      "GET /orders/group-counts": groupCountsAll,
    });

    const ordersUrls: string[] = [];
    await page.route(/\/api\/v1\/orders(\?|$)/, async (route) => {
      const url = route.request().url();
      ordersUrls.push(url);
      const u = new URL(url);
      const sortBy = u.searchParams.get("sort_by") ?? "updated_at";
      const sortOrder = u.searchParams.get("sort_order") ?? "desc";
      const sorted = [...allOrders].sort((a, b) => {
        const av = (a as unknown as Record<string, unknown>)[sortBy];
        const bv = (b as unknown as Record<string, unknown>)[sortBy];
        if (av === bv) return 0;
        const cmp =
          typeof av === "number" && typeof bv === "number"
            ? av - bv
            : String(av).localeCompare(String(bv));
        return sortOrder === "asc" ? cmp : -cmp;
      });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(sorted),
      });
    });

    await page.goto("/orders");
    await expect(page.getByRole("heading", { name: /受注管理/ })).toBeVisible({
      timeout: 20_000,
    });

    // 初期 fetch（sort_by=updated_at, sort_order=desc）
    await expect.poll(() => ordersUrls.length, { timeout: 5_000 }).toBeGreaterThan(0);
    expect(ordersUrls[ordersUrls.length - 1]).toContain("sort_by=updated_at");
    expect(ordersUrls[ordersUrls.length - 1]).toContain("sort_order=desc");

    // sort_by を total_amount に切替（ADR-044: testid 経由）
    await page.getByTestId("orders-sort-by").selectOption("total_amount");
    await expect
      .poll(() => ordersUrls[ordersUrls.length - 1] ?? "", { timeout: 5_000 })
      .toContain("sort_by=total_amount");

    // sort_order を asc にトグル
    await page.getByTestId("orders-sort-order").click();
    await expect
      .poll(() => ordersUrls[ordersUrls.length - 1] ?? "", { timeout: 5_000 })
      .toContain("sort_order=asc");
  });
});
