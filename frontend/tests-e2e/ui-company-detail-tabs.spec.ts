/**
 * CompanyDetailPage のタブ切り替え挙動検証
 *
 * 目的:
 *   4 タブ（Basic info / Address / Contacts / Channels）が
 *   クリックで正しく切り替わることをユーザー操作レベルで確認する。
 *
 * 注記:
 *   CSS ピクセル値（padding / border-radius / display 等）の検証は
 *   レイアウト変更で壊れやすいため削除済み（2026-05-29）。
 *   Storybook visual regression に委ねる。
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

test.describe("CompanyDetailPage tab navigation", () => {
  test("clicking each tab switches the active tab correctly", async ({ page }) => {
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

    // Address tab
    await page.locator(".tabs .tab").nth(1).click();
    await expect(page.locator(".tabs .tab.active")).toContainText(/Address|住所/);

    // Contacts tab
    await page.locator(".tabs .tab").nth(2).click();
    await expect(page.locator(".tabs .tab.active")).toContainText(/Contacts|担当者/);

    // Channels tab
    await page.locator(".tabs .tab").nth(3).click();
    await expect(page.locator(".tabs .tab.active")).toContainText(/Channels|チャ[ンネ]+ル/);

    // Back to Basic info tab
    await page.locator(".tabs .tab").nth(0).click();
    await expect(page.locator(".tabs .tab.active")).toContainText(/Basic|基本/);
  });
});
