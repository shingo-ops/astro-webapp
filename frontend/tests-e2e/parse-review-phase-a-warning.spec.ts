/**
 * spec.md v1.2 F9 (Sprint 9) — ParseReviewPage Phase A warning の Playwright E2E。
 *
 * AC9.6: 承認 UI で「Phase A: GS が真値」warning が常時表示される
 *         (AC9.1 と整合、approve 後の skipped_stock_update=true 時の toast も含む)
 */
import { expect, test } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi, type MockMap } from "./utils/api-mock";

const INBOUND_ID = 12345;

function baseMocks(opts: { skipped_stock_update: boolean }): MockMap {
  return {
    "GET /me/permissions": {
      permissions: ["dashboard.view"],
      is_super_admin: true,
      tenant_id: 6,
    },
    "GET /staff/me": {
      id: 1,
      primary_email: "review@salesanchor.jp",
      ui_preferences: {
        dark_mode: false,
        show_chat_menu: true,
        show_sales_menu: true,
        show_settings_menu: true,
        show_admin_menu: true,
        show_sidebar: true,
      },
    },
    [`GET /super-admin/parse-review/${INBOUND_ID}`]: {
      id: INBOUND_ID,
      discord_message_id: "msg-001",
      discord_channel_id: "ch-001",
      supplier_id: 1,
      supplier_name: "テスト仕入元",
      raw_content: "リザードン 3",
      parse_status: "parsed_rule_only",
      parse_engine: "rule_v1",
      parse_result_json: {
        items: [
          {
            product_id: 100,
            delta_qty: 3,
            alias_text: "リザードン",
            notes: null,
          },
        ],
        excludes: [],
        unparsed: [],
        skipped: [],
      },
      received_at: "2026-05-22T00:00:00Z",
      exclude_reason: null,
      operator_comment: null,
      operator_id: null,
      approved_at: null,
      llm_cost_usd: null,
      created_at: "2026-05-22T00:00:00Z",
      updated_at: "2026-05-22T00:00:00Z",
      version: 0,
    },
    [`POST /super-admin/parse-review/${INBOUND_ID}/approve`]: {
      inbound_id: INBOUND_ID,
      parse_status: "approved",
      version: 1,
      movements: [
        {
          movement_id: 1,
          product_id: 100,
          delta_qty: 3,
          before_qty: 0,
          after_qty: 3,
        },
      ],
      skipped_count: 0,
      skipped_stock_update: opts.skipped_stock_update,
      phase: opts.skipped_stock_update ? "A" : "B",
    },
  };
}

test.describe("Sprint 9 / F9 v1.2 — ParseReviewPage Phase A warning", () => {
  test("AC9.6: Phase A warning banner が常時表示される (画面ロード直後)", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, baseMocks({ skipped_stock_update: true }));
    await page.goto(`/super-admin/inbound/${INBOUND_ID}/review`);

    // 常時表示の Phase A warning banner
    const banner = page.getByTestId("phase-a-warning-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText(/Phase A|GS|spreadsheet|並走/i);
  });

  test("AC9.6: approve 後に skipped_stock_update=true の toast 警告が表示される", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, baseMocks({ skipped_stock_update: true }));
    await page.goto(`/super-admin/inbound/${INBOUND_ID}/review`);

    // 承認ボタンをクリック
    await page.getByText(/承認して在庫反映|approve/i).first().click();

    // skipped_stock_update=true の場合、warning toast が出る
    const toast = page.getByTestId("phase-a-warning-toast");
    await expect(toast).toBeVisible();
    await expect(toast).toContainText(/Phase A|stock_quantity|更新されません|not updated/i);
  });

  test("AC9.6 補完: skipped_stock_update=false の場合は banner のみ、toast なし", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, baseMocks({ skipped_stock_update: false }));
    await page.goto(`/super-admin/inbound/${INBOUND_ID}/review`);

    // 常時 banner はある
    await expect(page.getByTestId("phase-a-warning-banner")).toBeVisible();

    // approve 実行
    await page.getByText(/承認して在庫反映|approve/i).first().click();

    // skipped_stock_update=false の場合 toast は表示されない
    await expect(page.getByTestId("phase-a-warning-toast")).toHaveCount(0);
  });
});
