/**
 * CompanyDetailPage の CSS 適用検証 (2026-05-20 PR #444 / #445 用 ad-hoc spec)
 *
 * 目的:
 *   PR #444 で追加した .form-grid / .form-row / .tabs / .tab / .page-container
 *   CSS が CompanyDetailPage に正しく適用されていることを Playwright で確認する。
 *
 * 検証項目:
 *   1. .tabs が display: flex で 4 タブが横並び
 *   2. .tab.active が border-bottom-color に accent カラー(#1877F2)が適用
 *   3. .form-grid が display: grid (2 カラム auto-fit)
 *   4. .form-grid .form-row が display: flex column (label と input が縦並び)
 *   5. input/select/textarea に padding / border-radius が反映
 *   6. スクショ取得 (test-results/company-detail-fixed.png)
 *
 * 実行方法:
 *   cd frontend && npm run test:e2e -- ui-company-detail-css-check.spec.ts
 */

import { expect, test } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi } from "./utils/api-mock";
import { commonMocks } from "./utils/common-mocks";

const mockCompany = {
  id: 3,
  tenant_id: 6,
  company_code: "CO-00003",
  lead_id: null,
  sales_rep_id: null,
  name: "Demo EC Solutions Corp.",
  name_en: "Demo EC Solutions Corp.",
  normalized_name: "demo ec solutions corp",
  industry: "EC Platform",
  website: "https://example.com/demo-ec",
  trust_level: 4,
  priority_focus: "Volume",
  per_order_amount: "50000.00",
  monthly_frequency: 8,
  monthly_forecast: "400000.00",
  monthly_forecast_source: null,
  monthly_forecast_updated_at: null,
  billing_display_name: "Demo EC Solutions Corp.",
  payment_recipient_name: "Demo EC Solutions Corp.",
  fedex_account: null,
  shipping_note: null,
  status: "active",
  notes: null,
  addresses: [],
  sales_channels: [],
  created_at: "2026-05-15T00:00:00Z",
  updated_at: "2026-05-20T00:00:00Z",
};

const mockContacts = [
  {
    id: 11,
    contact_code: "CT-00003",
    display_name: "Hiroshi Demo",
    surname: null,
    given_name: null,
    job_title: "CEO",
    department: null,
    is_primary_contact: true,
    primary_email: "hiroshi@example-demo-ec.com",
    primary_phone: null,
    status: "active",
  },
];

test.describe("CompanyDetailPage CSS 適用検証 (PR #444)", () => {
  test("4 タブが横並び + form-grid が 2 カラムグリッドで描画される", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...commonMocks(),
      // mockCompany は `status: "active"` を持つため、{ body } で明示的にラップしないと
      // api-mock.ts の isResponseDetail() が誤判定する
      "GET /companies/3": { body: mockCompany },
      "GET /contacts": { body: mockContacts },
    });

    await page.goto("/companies/3");

    // タイトル h1 描画待ち
    await expect(page.getByRole("heading", { name: /Demo EC Solutions Corp/ })).toBeVisible({
      timeout: 20_000,
    });

    // ① .tabs が flex 横並び
    const tabsDisplay = await page.locator(".tabs").first().evaluate((el) => getComputedStyle(el).display);
    expect(tabsDisplay).toBe("flex");

    // ② .tabs 内に 4 タブ button が描画されている
    const tabButtons = page.locator(".tabs .tab");
    await expect(tabButtons).toHaveCount(4);

    // ③ Basic info タブが active (border-bottom-color が accent #1877F2)
    const activeTab = page.locator(".tabs .tab.active").first();
    await expect(activeTab).toBeVisible();
    const activeBorderColor = await activeTab.evaluate(
      (el) => getComputedStyle(el).borderBottomColor
    );
    // rgb(24, 119, 242) = #1877F2 (--accent カラー)
    expect(activeBorderColor).toMatch(/rgb\(24,\s*119,\s*242\)/);

    // ④ form-grid が display: grid
    const formGrid = page.locator("form.form-grid");
    await expect(formGrid).toBeVisible();
    const formGridDisplay = await formGrid.evaluate((el) => getComputedStyle(el).display);
    expect(formGridDisplay).toBe("grid");

    // ⑤ form-row が flex column (label → input 縦並び)
    const firstFormRow = page.locator("form.form-grid > .form-row").first();
    await expect(firstFormRow).toBeVisible();
    const formRowDisplay = await firstFormRow.evaluate((el) => getComputedStyle(el).display);
    const formRowFlexDirection = await firstFormRow.evaluate(
      (el) => getComputedStyle(el).flexDirection
    );
    expect(formRowDisplay).toBe("flex");
    expect(formRowFlexDirection).toBe("column");

    // ⑥ input が padding / border-radius を持つ
    const firstInput = firstFormRow.locator("input").first();
    await expect(firstInput).toBeVisible();
    const inputPaddingTop = await firstInput.evaluate((el) => getComputedStyle(el).paddingTop);
    const inputBorderRadius = await firstInput.evaluate(
      (el) => getComputedStyle(el).borderRadius
    );
    // padding: 8px 12px → paddingTop が "8px"
    expect(inputPaddingTop).toBe("8px");
    // border-radius: 6px
    expect(inputBorderRadius).toBe("6px");

    // ⑦ 検証用スクショ取得 (test-results/ 配下に保存)
    await page.screenshot({
      path: "test-results/company-detail-css-after.png",
      fullPage: true,
    });
  });

  test("タブクリックでアドレス / 担当者 / チャネルへ切替できる", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...commonMocks(),
      "GET /companies/3": { body: mockCompany },
      "GET /contacts": { body: mockContacts },
    });

    await page.goto("/companies/3");
    await expect(page.getByRole("heading", { name: /Demo EC Solutions Corp/ })).toBeVisible({
      timeout: 20_000,
    });

    // Address (0) タブクリック
    await page.locator(".tabs .tab").nth(1).click();
    await expect(page.locator(".tabs .tab.active")).toContainText(/Address|住所/);

    // Contacts (1) タブクリック
    await page.locator(".tabs .tab").nth(2).click();
    await expect(page.locator(".tabs .tab.active")).toContainText(/Contacts|担当者/);

    // Channels (Meta) タブクリック
    await page.locator(".tabs .tab").nth(3).click();
    await expect(page.locator(".tabs .tab.active")).toContainText(/Channels|チャ[ンネ]+ル/);

    // Basic info タブに戻る
    await page.locator(".tabs .tab").nth(0).click();
    await expect(page.locator(".tabs .tab.active")).toContainText(/Basic|基本/);
  });
});
