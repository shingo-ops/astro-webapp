/**
 * Scene 1: Intro — SalesAnchor Dashboard Overview
 *
 * 撮影台本対応: docs/META_APP_REVIEW_SCREENCAST_SCRIPT.md §2 (0:00–0:30)
 *
 * 目的:
 *   - LoginPage の DOM 要素（Email / Password / ログインボタン）が描画される
 *   - 認証 bypass 後、Dashboard ('/') が新構造（タブ・期間・固定/期間連動エリア）で表示される
 *   - 上段ブランドバー + 主要メニュー（リード / 在庫 / 管理 / その他）が描画される
 *
 * 変更履歴:
 *   2026-05-25: ダッシュボード強化（タブ・期間フィルター・目標・着地予測）に合わせて更新
 */

import { expect, test } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi } from "./utils/api-mock";
import { commonMocks } from "./utils/common-mocks";

/** 新ダッシュボード用 API モック群 */
function dashboardMocks() {
  return {
    // 目標サマリー（個人・チーム）— GoalSummary 型に合わせた形式
    "GET /goals/summary": { monthly: [], weekly: [] },
    // フォローアップリマインド
    "GET /analytics/followups": {
      overdue: [],
      due_today: [],
      upcoming: [],
      stalled: [],
    },
    // 着地予測
    "GET /analytics/forecast": {
      forecast_amount: 3200000,
      won_amount: 1800000,
      open_deal_count: 4,
      period_start: "2026-05-01",
      period_end: "2026-05-31",
    },
    // 滞留商談アラート
    "GET /analytics/stalled-deals": {
      stalled_count: 0,
      stalled_deals: [],
    },
    // 月次売上グラフ（Sprint 2 追加）
    "GET /analytics/monthly-revenue": {
      entries: [
        { month: "2026-01", actual: 3200000, forecast: null, remaining: 0, is_current: false },
        { month: "2026-02", actual: 2800000, forecast: null, remaining: 0, is_current: false },
        { month: "2026-03", actual: 4100000, forecast: null, remaining: 0, is_current: false },
        { month: "2026-04", actual: 3600000, forecast: null, remaining: 0, is_current: false },
        { month: "2026-05", actual: 1800000, forecast: 3200000, remaining: 1400000, is_current: true },
      ],
    },
    // 期間連動 KPI サマリー
    "GET /analytics/summary": {
      leads: {
        total: 18,
        converted: 7,
        excluded: 2,
        cv_rate: 38.9,
      },
      deals: {
        total: 12,
        active: 5,
        won: 4,
        win_rate: 44.4,
      },
      orders: {
        total_revenue: 5400000,
        order_count: 9,
        active_count: 2,
      },
      comparison: {
        leads_total: { pct: 12.5, direction: "up" },
        leads_cv_rate: { pct: -3.2, direction: "down" },
        deals_active: { pct: 0, direction: "flat" },
        deals_won: { pct: 25.0, direction: "up" },
        deals_win_rate: { pct: 8.1, direction: "up" },
        orders_revenue: { pct: 15.3, direction: "up" },
        orders_count: { pct: null, direction: "flat" },
      },
    },
  };
}

test.describe("Scene 1: Dashboard Overview", () => {
  test("LoginPage は Email / Password / ログインボタンが見える", async ({ page }) => {
    // 0:02–0:10 のフレーム: 認証前のログイン画面（Firebase auth bypass 不要）
    await page.goto("/login");

    await expect(page.getByLabel("メールアドレス")).toBeVisible();
    await expect(page.getByLabel("パスワード")).toBeVisible();
    await expect(page.getByRole("button", { name: "ログイン" })).toBeVisible();
  });

  test("認証済 user は Dashboard を見られ、新構造（タブ・期間・KPIセクション）が描画される", async ({
    page,
  }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...commonMocks(),
      ...dashboardMocks(),
    });

    // 0:12 の Dashboard 描画
    await page.goto("/");

    // h2 "ダッシュボード"
    await expect(page.getByRole("heading", { name: "ダッシュボード" })).toBeVisible({
      timeout: 20_000,
    });

    // 営業担当 / リード担当 / チーム タブが描画される（Sprint 1 でタブ構造変更）
    await expect(page.getByRole("button", { name: "営業担当" })).toBeVisible();
    await expect(page.getByRole("button", { name: "リード担当" })).toBeVisible();
    await expect(page.getByRole("button", { name: "チーム" })).toBeVisible();

    // 期間プルダウンが描画される
    const periodSelect = page.locator(".page-header-select");
    await expect(periodSelect).toBeVisible();

    // 固定エリア: 目標 / 着地予測 / フォローアップ の見出しが描画される（デフォルト: 営業担当ビュー）
    await expect(page.getByText("目標", { exact: true })).toBeVisible();
    await expect(page.getByText("今月の着地予測", { exact: true })).toBeVisible();
    await expect(page.getByText("フォローアップ", { exact: true })).toBeVisible();

    // チームタブに切り替えると全セクション（リード / 商談 / 受注）が表示される
    await page.getByRole("button", { name: "チーム" }).click();
    await expect(page.getByText("リード", { exact: true })).toBeVisible();
    await expect(page.getByText("商談", { exact: true })).toBeVisible();
    await expect(page.getByText("受注・売上", { exact: true })).toBeVisible();
  });

  test("0:18–0:25: メインナビにダッシュボード / 顧客管理 / 管理メニューが出ている", async ({
    page,
  }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...commonMocks(),
      ...dashboardMocks(),
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: "ダッシュボード" })).toBeVisible({
      timeout: 20_000,
    });

    // ADR-044: Meta Business Suite 風 UI 刷新 (ADR-022) で nav 構造が
    // `<nav class="mainnav">` から sidebar (`<nav class="sidebar-nav-items">`) に変更。
    // .sidebar-label は折り畳み時 opacity:0 のため、ホバーで展開してから検証する。
    const sidebar = page.locator("aside.sidebar-panel");
    await sidebar.hover();

    const nav = page.locator("nav.sidebar-nav-items");
    await expect(nav).toBeVisible();

    // sidebar 内の主要ラベル: ダッシュボード（NavLink） / 顧客管理（NavLink） / 管理センター（NavLink, 管理アコーディオン廃止）
    await expect(nav.getByText("ダッシュボード", { exact: true })).toBeVisible();
    await expect(nav.getByText("顧客管理", { exact: true })).toBeVisible();
    await expect(nav.getByText("管理センター", { exact: true })).toBeVisible();
  });
});
