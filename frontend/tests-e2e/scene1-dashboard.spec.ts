/**
 * Scene 1: Intro — SalesAnchor Dashboard Overview
 *
 * 撮影台本対応: docs/META_APP_REVIEW_SCREENCAST_SCRIPT.md §2 (0:00–0:30)
 *
 * 目的:
 *   - LoginPage の DOM 要素（Email / Password / ログインボタン）が描画される
 *   - 認証 bypass 後、Dashboard ('/') が KPI を伴って表示される
 *   - 上段ブランドバー + 主要メニュー（リード / 在庫 / 管理 / その他）が描画される
 *
 * 見せ場（撮影台本との対応）:
 *   - 0:02–0:10  Email/Password 入力フォームが映る → LoginPage DOM
 *   - 0:12       Dashboard 表示 → "ダッシュボード" 見出し + KPI カード
 *   - 0:18–0:25  メインナビ上の Inbox / Channels / Leads / Customers ハイライト
 */

import { expect, test } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi } from "./utils/api-mock";
import { commonMocks } from "./utils/common-mocks";
import { loadFixture } from "./utils/fixtures";

const dashboardFixture = loadFixture<{ customer_count: number }>("mock-dashboard.json");

test.describe("Scene 1: Dashboard Overview", () => {
  test("LoginPage は Email / Password / ログインボタンが見える", async ({ page }) => {
    // 0:02–0:10 のフレーム: 認証前のログイン画面（Firebase auth bypass 不要）
    await page.goto("/login");

    await expect(page.getByLabel("メールアドレス")).toBeVisible();
    await expect(page.getByLabel("パスワード")).toBeVisible();
    await expect(page.getByRole("button", { name: "ログイン" })).toBeVisible();
  });

  test("認証済 user は Dashboard を見られ、KPI が描画される", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...commonMocks(),
      "GET /dashboard": dashboardFixture,
    });

    // 0:12 の Dashboard 描画
    await page.goto("/");

    // h2 "ダッシュボード"
    await expect(page.getByRole("heading", { name: "ダッシュボード" })).toBeVisible({
      timeout: 20_000,
    });

    // 顧客 KPI（営業セクション）
    // ADR-044: i18n 化以降は t("dashboard.customers") = "顧客"
    await expect(page.getByText("顧客", { exact: true })).toBeVisible();
    // KPI 値が fixture と一致
    const customerCount = await page
      .locator(".kpi-card", { hasText: "顧客" })
      .locator(".kpi-value")
      .first()
      .innerText();
    expect(customerCount.trim()).toBe(String(dashboardFixture.customer_count));

    // コンバージョン率 / 成約金額 KPI も存在
    await expect(page.getByText("コンバージョン率")).toBeVisible();
    await expect(page.getByText("成約金額")).toBeVisible();
  });

  test("0:18–0:25: メインナビにダッシュボード / リード / 管理メニューが出ている", async ({
    page,
  }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...commonMocks(),
      "GET /dashboard": dashboardFixture,
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

    // sidebar 内の主要ラベル: ダッシュボード（NavLink） / リード（Accordion） / 管理（Accordion）
    await expect(nav.getByText("ダッシュボード", { exact: true })).toBeVisible();
    await expect(nav.getByText("リード", { exact: true })).toBeVisible();
    await expect(nav.getByText("管理", { exact: true })).toBeVisible();
  });
});
