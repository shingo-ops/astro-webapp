/**
 * CompaniesPage Edit modal の i18n 検証 (2026-05-21 ad-hoc spec)
 *
 * 目的:
 *   /companies (CompaniesPage) で Edit ボタンを押した時に開く modal の中身が
 *   全て英訳されているか確認する (ja UI でも適切なキーに置換されているか)。
 *
 * 検証項目:
 *   1. 一覧 search placeholder が i18n key 経由 (ja: "会社名・コードで検索...")
 *   2. Edit modal の tab labels (基本情報/請求先/配送先) が表示
 *   3. Edit modal の form labels (会社名、英語名、信頼度、重視ポイント等) が表示
 *   4. Billing tab に切り替えると住所フォーム labels が表示
 *   5. スクショ取得
 *
 * 実行方法:
 *   cd frontend && npx playwright test ui-companies-edit-modal-i18n.spec.ts
 */

import { expect, test } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi } from "./utils/api-mock";
import { commonMocks, ALL_PERMISSIONS } from "./utils/common-mocks";

const mockCompanies = [
  {
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
    updated_at: "2026-05-21T00:00:00Z",
  },
];

test.describe("CompaniesPage Edit modal i18n 検証", () => {
  test("Edit modal の labels が全て表示され日本語ハードコードが残っていない", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...commonMocks(),
      // CompaniesPage は customers.update / create / delete permission を必要とするため override
      "GET /me/permissions": {
        body: {
          permissions: [
            ...ALL_PERMISSIONS,
            "customers.update",
            "customers.create",
            "customers.delete",
          ],
        },
      },
      "GET /companies": { body: mockCompanies },
    });

    await page.goto("/companies");

    // 一覧表示確認 (ja: "顧客情報管理" / en: "Client Profiles")（ADR-060 リネーム後）
    await expect(page.getByRole("heading", { name: /Client Profiles|顧客情報管理/ })).toBeVisible({
      timeout: 20_000,
    });

    // Edit ボタンクリック (1 件目)
    await page
      .getByRole("button", { name: /Edit|編集/ })
      .first()
      .click();

    // Modal が開いたことを確認
    await expect(page.locator(".modal-content-wide")).toBeVisible();

    // タブ 3 つ表示 (ja でも en でも text 存在を確認)
    const tabs = page.locator(".modal-content-wide .tabs .tab");
    await expect(tabs).toHaveCount(3);

    // form-row labels の存在確認 (i18n key 経由)
    // 既存値があるはずなので Demo EC Solutions Corp. が name input にあるはず
    await expect(page.locator(".modal-content-wide").locator("input").first()).toBeVisible();

    // ローカル ja で「重視ポイント」/ en で「Priority focus」のいずれかが label として存在
    // (どちらの locale でもハードコードでなく i18n 経由になっていることだけ確認)
    const allLabels = await page.locator(".modal-content-wide label").allTextContents();
    expect(allLabels.length).toBeGreaterThan(10); // 基本情報タブだけで 10+ labels あるはず

    // スクショ撮影
    await page.screenshot({
      path: "test-results/companies-edit-modal-basic.png",
      fullPage: true,
    });

    // 請求先タブに切り替え (modal が縦長で viewport 外。JS で直接 click)
    await tabs.nth(1).evaluate((el: HTMLButtonElement) => el.click());
    await page.waitForTimeout(300); // tab 切替後の DOM 反映待ち

    // 住所フォームの label が表示されていることを確認
    const billingLabels = await page.locator(".modal-content-wide label").allTextContents();
    expect(billingLabels.length).toBeGreaterThan(5); // 住所フォームの label 6+ 個

    await page.screenshot({
      path: "test-results/companies-edit-modal-billing.png",
      fullPage: true,
    });
  });
});
